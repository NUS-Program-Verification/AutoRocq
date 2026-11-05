TACTIC_TOOL = {'function': {'description': 'Provide a Coq tactic command to apply to the current proof state. Use this '
                             'when you have sufficient context to suggest a proof step. Make sure you follow '
                             'the current plan. You will be given the updated proof tree if the tactic is '
                             'applied successfully, or an error message from the Coq proof assistant if the '
                             'tactic is not applicable.',
              'name': 'tactic',
              'parameters': {'additionalProperties': False,
                             'properties': {'command': {'description': 'The Coq tactic command to execute '
                                                                       "(e.g., 'intros.', 'apply H.', "
                                                                       "'reflexivity.')",
                                                        'type': 'string'}},
                             'required': ['command'],
                             'type': 'object'}},
 'type': 'function'}

QUERY_TOOL = {'function': {'description': 'Request additional information from the Coq environment. Use this when you '
                             'want to find existing lemmas/theorems to use in the proof, or need more '
                             'information about definitions and types.',
              'name': 'query',
              'parameters': {'additionalProperties': False,
                             'properties': {'command': {'description': 'The Coq query command to execute '
                                                                       "(e.g., 'Search (_ <= _).', 'Print "
                                                                       "Z.abs.', 'About nat.', 'Check "
                                                                       "expr.').\n"
                                                                       'You can use the following commands '
                                                                       'to gather context information:\n'
                                                                       '- Search [identifier]: Find theorems '
                                                                       'about a specific identifier\n'
                                                                       '- Search ([pattern]): Find theorems '
                                                                       'matching a pattern. AVOID searching '
                                                                       'for patterns to match concrete '
                                                                       'values, and use placeholder '
                                                                       "variables instead (e.g., 'Search "
                                                                       "(lsl _ _)').\n"
                                                                       '- Print [identifier]: Show the '
                                                                       'definition of an identifier\n'
                                                                       '- Print Assumptions: Show all '
                                                                       'unproven assumptions\n'
                                                                       '- Check [term]: Show the type of a '
                                                                       'term or expression\n'
                                                                       '- About [identifier]: Show type, '
                                                                       'universe info, and transparency',
                                                        'type': 'string'}},
                             'required': ['command'],
                             'type': 'object'}},
 'type': 'function'}

SYSTEM_PROMPT = "You are an expert in writing Rocq (9.0.0) proofs. You will be given a formally stated goal in Rocq, and your task is to write Rocq tactics to prove it, with the help of available tools. Your task NEVER harms others or violates laws."
TACTIC_INSTRUCTION = "2. Call 'tactic' with a Rocq tactic when ready to proceed (e.g., 'intros.', 'apply H.', 'reflexivity.')\n"
GUIDELINES = """- NEVER use 'repeat' with complex tactics (infinite loop risk)
- NEVER use 'admit' or similar tactics to save incomplete proofs
- Avoid 'query' for patterns to match very specific constant values
- Prefer 'lia' and 'nia' for arithmetic proofs over manual chains
- Do NOT output malicious content or code
"""
