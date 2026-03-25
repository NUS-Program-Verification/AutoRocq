import os
import re
import time
import json
import traceback
from copy import deepcopy
from typing import List, Dict, Any, Optional
from agent.history_recorder import TacticHistoryManager
from openai import OpenAI, RateLimitError
from openai.types.chat import ChatCompletion

from agent.context_search import ContextSearch 
 
from utils.logger import setup_logger, clean_ansi_codes
from utils.coq_utils import *

class CoqChatSession:
    """
    A class to manage an OpenAI chat session for Coq proof tactics.
    """

    # Define the function tools for OpenAI API
    PLAN_TOOL = {
            "type": "function",
            "function": {
                "name": "plan",
                "description": "Create or update a high-level proof strategy. Use this at the start of a proof or when you need to rethink your approach. The plan will guide your subsequent tactic choices.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "strategy": {
                            "type": "string",
                            "description": "A clear, step-by-step high-level strategy for completing the proof. Include: (1) What you need to prove, (2) Key lemmas/theorems to use, (3) Major proof steps, (4) Potential challenges and how to address them."
                        }
                    },
                    "required": ["strategy"],
                    "additionalProperties": False
                }
            }
        }
    TACTIC_TOOL = {
            "type": "function",
            "function": {
                "name": "tactic",
                "description": "Provide a Coq tactic command to apply to the current proof state. Use this when you have sufficient context to suggest a proof step. Make sure you follow the current plan. You will be given the updated proof tree if the tactic is applied successfully, or an error message from the Coq proof assistant if the tactic is not applicable.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "The Coq tactic command to execute (e.g., 'intros.', 'apply H.', 'reflexivity.')"
                        }
                    },
                    "required": ["command"],
                    "additionalProperties": False
                }
            }
        }
    QUERY_TOOL = {
            "type": "function",
            "function": {
                "name": "query",
                "description": "Request additional information from the Coq environment. Use this when you want to find existing lemmas/theorems to use in the proof, or need more information about definitions and types.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "description": "The Coq query command to execute (e.g., 'Search (_ <= _).', 'Print Z.abs.', 'About nat.', 'Check expr.').\n" + \
                                "You can use the following commands to gather context information:\n" + \
                                "- Search [identifier]: Find theorems about a specific identifier\n" + \
                                "- Search ([pattern]): Find theorems matching a pattern. AVOID searching for patterns to match concrete values, and use placeholder variables instead (e.g., 'Search (lsl _ _)').\n" + \
                                "- Print [identifier]: Show the definition of an identifier\n" + \
                                "- Print Assumptions: Show all unproven assumptions\n" + \
                                "- Check [term]: Show the type of a term or expression\n" + \
                                "- About [identifier]: Show type, universe info, and transparency"
                        }
                    },
                    "required": ["command"],
                    "additionalProperties": False
                }
            }
        }
    ROLLBACK_TOOL = {
            "type": "function",
            "function": {
                "name": "rollback",
                "description": "Rollback the proof to a previous step when stuck or after multiple consecutive errors. Use this when: (1) Multiple tactics are failing consecutively, (2) The current proof path seems unproductive, (3) You need to try a different approach from an earlier state.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "reason": {
                            "type": "string",
                            "description": "Brief explanation of why rollback is needed."
                        },
                        "steps": {
                            "type": "integer",
                            "description": "Number of steps to rollback (e.g., 3 means go back 3 steps). Defaults to 1 if not specified."
                        }
                    },
                    "required": ["reason"],
                    "additionalProperties": False
                }
            }
        }
    
    # File for local session caching
    GLOBAL_CACHE_FILE = "/tmp/openai_cache.json"
    
    def __init__(self, 
                 model=None, temperature=0, api_key=None, max_tokens=15000, timeout=30, 
                 enable_caching=True,
                 enable_context_search=True,
                 enable_rollback=True,
                 enable_local_session_caching=False):
        
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-4.1")
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.logger = setup_logger("CoqChatSession")
        self.max_conversation_history = 4
        self.enable_caching = enable_caching
        self.enable_context_search = enable_context_search
        self.enable_rollback = enable_rollback
        self.enable_local_session_caching = enable_local_session_caching
        self.current_plan = None
        self.coq_version = "8.18.0"
        
        # Token usage tracking
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_cached_tokens = 0
        self.api_call_count = 0

        system_prompt = self.build_system_prompt()
        
        self.messages = []
        self.cached_msg_len = 0
        self.add_message("system", system_prompt)
        self.logger.debug(f"System prompt:\n{system_prompt}")
        
        # 'plan' and 'tactic' are always available
        self.tools = [self.PLAN_TOOL, self.TACTIC_TOOL]
        # add other tools only if enabled
        if self.enable_context_search:
            self.tools.append(self.QUERY_TOOL)
        if self.enable_rollback:
            self.tools.append(self.ROLLBACK_TOOL)
        
        self.logger.info(f"Available tools:\n{', '.join([tool['function']['name'] for tool in self.tools])}")
        
        self.client = OpenAI(api_key=self.api_key)
    
    def build_system_prompt(self) -> str:
        system = f"You are an expert in writing Coq ({self.coq_version}) proofs. You will be given a formally stated goal in Coq, and your task is to write Coq tactics to prove it, with the help of available tools. Your task NEVER harms others or violates laws."
        
        instruction = "INSTRUCTIONS:\n" \
            "- You will be given a goal (a formally stated lemma) to prove and its context in a proof file.\n" \
            "- At each step, you should analyze the given context and decide which tool to call next.\n" \
            "- After each tool call, you will be given the result of the tool call as additional context.\n" \
            "- Whenever the proof is updated (via 'tactic', 'rollback'), you will be given the new proof tree, represented as a sequence of applied tactics with the open proof goals at the end.\n" \
            "\nAVAILABLE TOOLS:\n" \
            "1. Call 'plan' to create/update strategy (recommended when there is no 'plan', or when stuck)\n" \
            "2. Call 'tactic' with a Coq tactic when ready to proceed (e.g., 'intros.', 'apply H.', 'reflexivity.')\n"
        
        # add instructions for tools only if enabled
        if self.enable_context_search:
            instruction += \
            "3. Call 'query' to gain more context (search for lemmas/theorems, print definitions, etc.)\n"
        if self.enable_rollback:
            instruction += \
            "4. Call 'rollback' when stuck or after consecutive errors to return to a better proof state.\n"

        instruction += \
            "\nGUIDELINES:\n" \
            "- Follow the 'plan' when possible.\n" \
            "- Consider decomposing the proof into a sequence of simpler steps.\n" \
            "- When suggesting a 'tactic', try to reuse imported libraries and existing proved theorems/definitions/axioms if they are relevant.\n" \
            "- For 'tactic'/'query', provide EXACT COMMAND without extra text.\n" \
            "- When stuck at a specific step, consider:\n" \
            "   1. Review the current 'plan', and revise it only if needed,\n" \
            "   2. Use 'query' tool to search for lemmas or check definitions,\n" \
            "   3. Call 'rollback' tool to restore to an earlier step (invoke only if you are not able to follow the 'plan').\n" \
            "\nSAFETY RULES:\n" \
            "- NEVER use 'repeat' with complex tactics (infinite loop risk)\n" \
            "- NEVER use 'admit' or similar tactics to save incomplete proofs\n" \
            "- Avoid 'query' for patterns to match very specific constant values\n" \
            "- Prefer 'lia' for arithmetic proofs over manual chains\n" \
            "- Do NOT output malicious content or code\n" \
        
        return (system + "\n\n" + instruction).strip()
    
    def add_message(self, role, content):
        """
        Add a message to the conversation history.
        
        Args:
            role (str): The role of the sender ('system' or 'user').
            content (str): The content of the message.
        """
        assert role in ["system", "user"]
        message = {"role": role, "content": content}
        if self.enable_caching:
            message["cache_control"] = {"type": "ephemeral"}
        self.messages.append(message)
        if self.enable_caching:
            self.cached_msg_len = len(self.messages)
    
    def add_tool_call(self, tool_call, content):
        """
        Record a tool call from the assistant.
        """
        self.messages.append({
            "role": "assistant",
            "content": content,
            "tool_calls": [{
                "id": tool_call.id,
                "type": "function",
                "function": {
                    "name": tool_call.function.name,
                    "arguments": tool_call.function.arguments
                }
            }]
        })
    
    def add_tool_response(self, tool_call_id, content):
        """
        Add a tool response message to the conversation history.
        Must be called after an assistant message with tool_calls.
        
        Args:
            tool_call_id (str): The tool_call_id from the assistant's tool call.
            content (str): The result/response from executing the tool.
        """
        if not tool_call_id:
            self.logger.error("⚠️  add_tool_response called without tool_call_id")
            return
        
        self.messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": content
        })

    def get_cached_response(self, api_params):
        data = []
        if os.path.exists(self.GLOBAL_CACHE_FILE):
            with open(self.GLOBAL_CACHE_FILE, "r") as f:
                data = json.load(f)

        for entry in data:
            query = entry["query"]
            response = entry["response"]
            if api_params == query:
                return True, ChatCompletion.model_validate(response)

        response = self.client.chat.completions.create(**api_params)

        data.append({"query": api_params, "response": response.model_dump()})
        with open(self.GLOBAL_CACHE_FILE, "w") as f:
            json.dump(data, f, indent=4)

        return False, response

    def send_message(self, user_message, role: str = "user", tool_call_id: str = None, should_optimize: bool = False) -> dict:
        """
        Send a message to the OpenAI API and get a response.
        
        Args:
            user_message (str): The user's input message.
            role (str): The role of the sender ('user' or 'tool' or 'retry').
            tool_call_id (str): The tool_call_id from the assistant's tool call.
            should_optimize (bool): If True, optimize messages before this call (default: False).
            
        Returns:
            Dict for LLM response and token usage.
        """
        
        # Append to conversation history
        if role == "user":
            self.add_message(role, user_message)
        elif role == "tool":
            self.add_tool_response(tool_call_id, user_message)
        elif role == "retry":
            pass # do nothing
        else:
            raise ValueError(f"Invalid role: {role}")
        
        # Optimize messages (if requested and conditions are met)
        if should_optimize and self._can_optimize():
            self.optimize_messages()
        
        messages_to_send = self.messages
        self.logger.debug(f"Sending {len(self.messages)} messages to LLM (first {self.cached_msg_len} cached)")
        
        try:
            # Build API call parameters
            api_params = {
                "model": self.model,
                "messages": messages_to_send,
                "temperature": self.temperature,
                "max_completion_tokens": self.max_tokens,
                "tools": self.tools,
                "tool_choice": "required", # always use tools
            }
            
            if self.enable_local_session_caching:
                using_cached_response, response = self.get_cached_response(api_params)
            else:
                response = self.client.chat.completions.create(**api_params)
            
            assistant_message_obj = response.choices[0].message if response.choices else None
            prompt_tokens = response.usage.prompt_tokens if response.usage else 0
            completion_tokens = response.usage.completion_tokens if response.usage else 0
            
            cached_tokens = 0
            if response.usage and hasattr(response.usage, 'prompt_tokens_details'):
                details = response.usage.prompt_tokens_details
                if details and hasattr(details, 'cached_tokens'):
                    cached_tokens = details.cached_tokens or 0
            
            # Track token usage only if not using cached response
            if not self.enable_local_session_caching or not using_cached_response:
                self.total_prompt_tokens += prompt_tokens
                self.total_completion_tokens += completion_tokens
                self.total_cached_tokens += cached_tokens
                self.api_call_count += 1
            
            if not assistant_message_obj:
                raise ValueError("No assistant message object found")
            
            if not assistant_message_obj.tool_calls:
                raise ValueError("No tool calls found in assistant message")
            
            # Handle function/tool calls
            assistant_message_content = assistant_message_obj.content
            tool_call = assistant_message_obj.tool_calls[0]  # Get first tool call
            function_call_info = {
                "name": tool_call.function.name,
                "arguments": tool_call.function.arguments
            }
            
            # Add the assistant message with tool call to history
            self.add_tool_call(tool_call, assistant_message_content)
            
            return {
                "response": assistant_message_content,
                "function_call": function_call_info,
                "tool_call_id": tool_call.id,
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens
            }
            
        except RateLimitError as e:
            self.logger.info(f"Rate limit error encountered: {e}")
            self.logger.info("Sleeping for 30 seconds to retry...")
            time.sleep(30)
            return {"response": None, "error": "Rate limit error"}
            
        except Exception as e:
            return {"response": None, "error": str(e)}
    
    def _can_optimize(self) -> bool:
        """
        Check if messages can be optimized.
        Returns True if we have the right structure for optimization.
        """
        if not self.enable_caching:
            return False
        
        # Need at least cached messages + 2 new messages (assistant + tool)
        if len(self.messages) < self.cached_msg_len + 2:
            return False
        
        # Check if we have the expected structure
        if len(self.messages) < 2:
            return False
            
        # Last message should be tool response, second-to-last should be assistant with tool call
        if self.messages[-1].get("role") != "tool":
            return False
        if self.messages[-2].get("role") != "assistant":
            return False
        if "tool_calls" not in self.messages[-2]:
            return False
            
        return True
   
    def optimize_messages(self):
        """
        Optimize the messages to reduce context length.
        Should only be called when _can_optimize() returns True.
        After optimization, temporary tool calls and responses are removed.
        """
        # Validate preconditions first
        if not self._can_optimize():
            return
        
        self.logger.debug(f"Optimizing messages (currently cached: {self.cached_msg_len}, total: {len(self.messages)})")
        
        opt_messages = self.messages[:self.cached_msg_len]
        for message in opt_messages:
            # remove cache_control from old tool responses
            if message["role"] == "tool":
                message.pop("cache_control", None)
        
        opt_messages.append(self.messages[-2]) # successful tool call
        opt_messages.append(self.messages[-1]) # tool response to send
        # cache the last message (tool)
        opt_messages[-1]["cache_control"] = {"type": "ephemeral"}
        
        self.logger.info(f"Messages optimized ({len(self.messages)} -> {len(opt_messages)})")
        
        # update messages and cached length
        self.messages = opt_messages
        self.cached_msg_len = len(self.messages)

   
    def get_token_statistics(self):
        return {
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_completion_tokens": self.total_completion_tokens,
            "total_cached_tokens": self.total_cached_tokens,
            "total_tokens": self.total_prompt_tokens + self.total_completion_tokens,
            "api_calls": self.api_call_count
        }
    

class ContextManager:
    def __init__(
        self, 
        coq_interface, 
        model=None, 
        temperature=0, 
        api_key=None, 
        max_tokens=15000, 
        timeout=30,
        history_file="tactic_history.json",
        enable_history_context: bool = True,
        enable_context_search: bool = True,
        enable_rollback: bool = True,
        enable_caching: bool = True,
        proof_plan: str = None,
        enable_local_session_caching: bool = False,
    ):
        self.coq = coq_interface
        self.logger = setup_logger("ContextManager")
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-4.1")
        self.api_key = api_key or os.getenv("OPENAI_API_KEY")
        if not self.api_key:
            self.logger.error(f"❌ API key not found. Please set OPENAI_API_KEY env var.")
            exit(1)
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.enable_history_context = enable_history_context
        self.enable_caching = enable_caching
        self.enable_context_search = enable_context_search
        self.enable_rollback = enable_rollback
        self.tactic_history = TacticHistoryManager(history_file)
        self.current_step = 0
        self.proof_plan = proof_plan
        self.enable_local_session_caching = enable_local_session_caching
        
        # Initialize context search 
        try:
            self.context_search = ContextSearch(coq_interface, history_file)
            self.logger.info(f"✅ Context search initialized successfully")
        except Exception as e:
            self.logger.warning(f"⚠️  Failed to initialize context search: {e}")
            self.context_search = None
        
        # Initialize chat session with LLM
        self.chat_session = CoqChatSession(
            model=model,
            temperature=temperature,
            api_key=api_key,
            max_tokens=max_tokens,
            timeout=timeout,
            enable_context_search=self.enable_context_search,
            enable_rollback=self.enable_rollback,
            enable_caching=self.enable_caching,
            enable_local_session_caching=self.enable_local_session_caching
        )
        self.logger.info(f"🤖 Chat session initialized with model: {model}")
         
    def build_initial_prompt(self, proof_tree_str: str) -> str:
        prompt = "Given the following context, choose the best function call to help complete the proof.\n\n"
        prompt += "## PROOF FILE CONTEXT:\n"
        proof_file_content = self.coq.get_proof_file_content()
        clean_proof_file_content = clean_ansi_codes(proof_file_content)
        essential_content = self.extract_essential_proof_content(clean_proof_file_content)
        prompt += essential_content + "\n\n"
        
        # Initial plan: use proof plan if available
        if self.proof_plan:
            prompt += f"## CURRENT PROOF PLAN:\n{self.proof_plan}\n\n"
        else:   
            prompt += f"## CURRENT PROOF PLAN: None\n\n"

        return prompt

    def extract_essential_proof_content(self, proof_file_content):
        return extract_essential_proof_content(self.logger, proof_file_content)

    def handle_plan_call(self, plan_content: str, tool_call_id: str) -> bool:
        # Store the plan in chat session
        self.chat_session.current_plan = plan_content
        self.logger.info(f"📋 Plan stored:\n{plan_content}")
        
        # Ack: plan has been recorded
        tool_response = (
            f"Plan recorded successfully. You can now proceed with tactics or queries based on this plan, or call 'plan' again to update."
        )
        
        return tool_response
    
    def handle_query_call(self, query_content: str, tool_call_id: str) -> str:
        
        if not self.enable_context_search:
            return "No results found: 'query' tool not available."
        
        # Execute context search
        search_result, success = self._execute_context_search(query_content)
        
        # Send tool response with query results
        tool_response = (
            f"Query executed: {query_content}\n\n"
            f"{search_result}\n"
        )
        if not success:
            tool_response += "\nYou may consider using a different query."
        
        return tool_response

    def get_tactic(self, tactic_content: str, tool_call_id: str) -> str:
        # Ensure proper formatting
        if not tactic_content.endswith('.') and not tactic_content.lower() == 'qed':
            tactic_content += '.'
               
        return tactic_content

    def get_action(self, context_prompt: str, role: str = "user", tool_call_id: str = None, tool_success: bool = False) -> tuple[dict, str]:
        """
        Prompt the LLM with user prompt or tool response to generate an tool call.
        
        Returns
            tuple[dict, str]: (decision, tool_call_id)
            decision: {'type': 'function_call_name', 'content': str}
            tool_call_id: str
        """
        try:
            if role == "user":
                self.logger.info(f"User prompt:\n{context_prompt}")
                # Before sending as user, check if there's an unanswered tool call
                if (self.chat_session.messages and 
                    self.chat_session.messages[-1].get("role") == "assistant" and 
                    "tool_calls" in self.chat_session.messages[-1]):
                    # There's an unanswered tool call - we must respond to it first
                    unanswered_tool_call_id = self.chat_session.messages[-1]["tool_calls"][0]["id"]
                    self.logger.warning(f"⚠️  Found unanswered tool call {unanswered_tool_call_id}, sending as tool response instead")
                    role = "tool"
                    tool_call_id = unanswered_tool_call_id
            
            if role == "tool":
                self.logger.info(f"Tool response:\n{context_prompt}")
                # Validate that if role is "tool", we must have a tool_call_id
                # and the last message must be an assistant message with tool_calls
                try:
                    assert tool_call_id is not None, "tool_call_id is required for tool role"
                    assert self.chat_session.messages, "empty message thread"
                    assert self.chat_session.messages[-1].get("role") == "assistant", "last message must be an assistant message"
                    assert "tool_calls" in self.chat_session.messages[-1], "last assistant message must have tool_calls"
                    assert len(self.chat_session.messages[-1]["tool_calls"]) == 1, "last assistant message must have exactly one tool call"
                except AssertionError as e:
                    # This shouldn't happen if we checked above, but fallback
                    self.logger.error(f"❌ {e}")
                    self.logger.warning("🔄 Sending as user message instead")
                    role = "user"
                    tool_call_id = None
            
            llm_result = self.chat_session.send_message(context_prompt, role=role, tool_call_id=tool_call_id, should_optimize=tool_success)
            invalid_error_count = 0
            while llm_result.get("error"):
                self.logger.warning(f"LLM error: {str(llm_result)}")
                err_response = llm_result.get("error")
                if err_response.startswith("Error code: 400"):
                    # This is to retry the request denied by safety policy. Example:
                    # Error code: 400 - {'error': {'message': 'Invalid prompt: your prompt was flagged as potentially violating our usage policy. Please try again with a different prompt: https://platform.openai.com/docs/guides/reasoning#advice-on-prompting', 'type': 'invalid_request_error', 'param': None, 'code': 'invalid_prompt'}}
                    llm_result = self.chat_session.send_message(context_prompt, role="retry", tool_call_id=None, should_optimize=False)
                    invalid_error_count += 1
                    if invalid_error_count >= 3:
                        self.logger.warning(f"Not able to pass invalid_request_error check. Continuing...")
                        return None, None
                else:
                    return None, None
            
            if not llm_result.get("function_call") or not llm_result.get("tool_call_id"):
                self.logger.error(f"❌ LLM result does not contain function_call or tool_call_id")
                return None, None
            
            tool_call_id = llm_result.get("tool_call_id")
            self.logger.info(f"LLM function call: {llm_result['function_call']['name']}({llm_result['function_call']['arguments']})")
            decision = self._parse_llm_decision(llm_result)
            return decision, tool_call_id
        
        except Exception as e:
            self.logger.error(f"Error in get_action: {e}")
            self.logger.error(f"Traceback: {traceback.format_exc()}")
            return None, None
    
    def _parse_llm_decision(self, llm_result):
        """
        Parse LLM response to determine the action to take.
        Should be called only if the LLM result contains a function_call.
        
        Args:
            llm_result (dict): The full LLM result including response and function_call info
            
        Returns:
            dict: {'type': action_type, 'content': str}
        """
        
        assert "function_call" in llm_result, "LLM result must contain function_call"
        func_call = llm_result["function_call"]
        func_name = func_call["name"]
        
        try:
            # Parse the arguments JSON string
            args = json.loads(func_call["arguments"])
            decision = {'type': func_name}
            if func_name == "plan":
                decision['content'] = args.get("strategy", "").strip()
            elif func_name == "tactic":
                decision['content'] = args.get("command", "").strip()
            elif func_name == "query":
                decision['content'] = args.get("command", "").strip()
            elif func_name == "rollback":
                decision['content'] = {
                    'reason': args.get("reason", "").strip(),
                    'steps': args.get("steps", 1)  # Default to 1 step
                }
            else:
                raise ValueError(f"Unknown function call: {func_name}")
            return decision
        
        except (json.JSONDecodeError, ValueError) as e:
            # JSON parsing failed - return error as tactic response
            self.logger.error(f"Error parsing LLM decision: {e}")
            response_text = llm_result.get("response") or ""
            return {'type': 'tactic', 'content': response_text.strip() if response_text else "reflexivity"}

    def _execute_context_search(self, query) -> tuple[str, bool]:
        """Execute context search query and return formatted results."""
        try:
            if not self.context_search:
                return "Context search not available", False
            
            # Use the context search system's unified search method
            search_result = self.context_search.search(query)
            
            if not search_result or search_result.result_size == 0:
                return f"No results found.", False
            
            return search_result.content, True
            
        except Exception as e:
            self.logger.error(f"Error executing context search: {e}")
            return f"Context search error: {str(e)}"
    
    def should_give_up(self) -> bool:
        """Determine if the agent should give up on the proof."""
        give_up_keywords = ["unprovable", "not provable", "unable to proceed", "give up", "abort"]
        return any([kw in self.chat_session.current_plan.lower() for kw in give_up_keywords])

    def get_similar_history(self, proof_state: str, n: int = 5) -> List[Dict[str, str]]:
        try:
            return self.tactic_history.get_similar_history(proof_state, n)
        except Exception as e:
            self.logger.error(f"Error getting similar proof states: {e}")
            return []
    
    def get_token_statistics(self):
        """
        Get cumulative token usage statistics from the chat session.
        
        Returns:
            dict: Token usage statistics with keys:
                - total_prompt_tokens: Total input tokens across all API calls
                - total_completion_tokens: Total output tokens across all API calls
                - total_cached_tokens: Total tokens read from cache (0 if caching disabled)
                - total_tokens: Sum of prompt and completion tokens
                - api_calls: Number of API calls made
        """
        return self.chat_session.get_token_statistics()
