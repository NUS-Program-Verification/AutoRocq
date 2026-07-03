import json
from typing import List, Optional, Dict, Any
from datetime import datetime
from graphviz import Digraph
from utils.logger import setup_logger

class ProofTreeNode:
    def __init__(
        self,
        tactic: str,
        goals_before: str,
        goals_after: str,
        hypotheses_before: str,
        hypotheses_after: str,
        step_number: int,
        parent: 'ProofTreeNode' = None,
        subgoal_index: Optional[int] = None,
        status: str = "Applied",  # "Active", "Applied", "Proved"
        node_type: str = "tactic",  # "tactic", "subgoal"
        source: str = "agent"  # "agent" or "user"
    ):
        self.tactic = tactic
        self.goals_before = goals_before
        self.goals_after = goals_after
        self.hypotheses_before = hypotheses_before
        self.hypotheses_after = hypotheses_after
        self.step_number = step_number
        self.parent = parent
        self.children = []
        self.subgoal_index = subgoal_index
        self.status = status
        self.node_type = node_type  # "tactic" or "subgoal"
        self.source = source  # "agent" or "user"
        self.logger = setup_logger("ProofTreeNode")

    def add_child(self, child: 'ProofTreeNode'):
        self.children.append(child)

    def is_leaf(self) -> bool:
        """Check if this is a leaf node (no children)."""
        return len(self.children) == 0

    def is_subgoal_node(self) -> bool:
        """Check if this is a subgoal intermediate node."""
        return self.node_type == "subgoal"

    def to_dict(self):
        return {
            'tactic': self.tactic,
            'step_number': self.step_number,
            'subgoal_index': self.subgoal_index,
            'status': self.status,
            'node_type': self.node_type,
            'source': self.source,
            'goals_before': self.goals_before,
            'goals_after': self.goals_after if self.is_leaf() else "",  # Only show goals_after for leaf nodes
            'hypotheses_before': self.hypotheses_before,
            'hypotheses_after': self.hypotheses_after if self.is_leaf() else "",  # Only show hypotheses_after for leaf nodes
            'children': [c.to_dict() for c in self.children]
        }


class ProofTree:
    def __init__(self):
        self.root = None
        self.open_subgoals = []  # Stack of (subgoal_node, subgoal_index, subgoal_content)
        self.active_node = None
        self.logger = setup_logger("ProofTree")

    def add_node(
        self,
        tactic: str,
        goals_before: str,
        goals_after: str,
        hypotheses_before: str,
        hypotheses_after: str,
        step_number: int,
        subgoals_after: list = None,
        parent: Optional['ProofTreeNode'] = None
    ) -> Optional['ProofTreeNode']:
        """
        Add a new node to the proof tree.
        If parent is None, assumes this is the root node.
        """
        new_node = ProofTreeNode(
            tactic=tactic,
            goals_before=goals_before,
            goals_after=goals_after,
            hypotheses_before=hypotheses_before,
            hypotheses_after=hypotheses_after,
            step_number=step_number,
            parent=parent
        )
        
        if parent is None:
            # This is the root node
            self.root = new_node
            self.logger.info(f"🌳 Created root node: {tactic}")
            
            # Initialize open_subgoals with the root node (NOT a tuple!)
            if subgoals_after:
                self.open_subgoals = [new_node]
                self.logger.info(f"🌳 Initialized open_subgoals with root node")
            
        else:
            # Add as child to parent
            parent.children.append(new_node)
            self.logger.info(f"🌳 Added node as child: {tactic}")
        
        return new_node

    def add_branching_node(
        self,
        tactic: str,
        goals_before: str,
        goals_after: str,
        hypotheses_before: str,
        hypotheses_after: str,
        step_number: int,
        subgoals: list
    ) -> Optional['ProofTreeNode']:
        """
        Add a branching node that creates multiple subgoals.
        Each subgoal extracts ONLY its conclusion (the final goal to prove),
        not the full forall/let context.
        """
        if not self.open_subgoals:
            self.logger.warning("No open subgoals to branch from")
            return None
        
        parent_subgoal = self.open_subgoals[0]
        
        if not isinstance(parent_subgoal, ProofTreeNode):
            self.logger.error(f"❌ Parent subgoal is not a ProofTreeNode! Type: {type(parent_subgoal)}")
            raise TypeError(f"Expected ProofTreeNode but got {type(parent_subgoal)}")
        
        def extract_goal_conclusion(goal) -> tuple:
            """
            Extract ONLY the final conclusion to prove, stripping forall/let bindings.
            
            For example, from:
              forall x y, let z := x + y in P(z)
            Extract only:
              P(z)
            
            Returns: (conclusion_str, hypotheses_str)
            """
            if hasattr(goal, 'ty'):
                goal_full = str(goal.ty).strip()
                
                # Extract hypotheses
                hyps_str = ""
                if hasattr(goal, 'hyps') and goal.hyps:
                    hyps_lines = []
                    for hyp in goal.hyps:
                        if hasattr(hyp, 'names') and hasattr(hyp, 'ty'):
                            names_str = ', '.join(hyp.names)
                            hyps_lines.append(f"{names_str}: {hyp.ty}")
                    hyps_str = '\n'.join(hyps_lines)
                
                # Parse the goal to extract conclusion
                # Strategy: Look for the final '->' or just use the whole thing if no arrows
                
                # Split by '->' to find the conclusion (last part)
                parts = goal_full.split('->')
                if len(parts) > 1:
                    # The conclusion is after the last '->'
                    conclusion = parts[-1].strip()
                else:
                    # No '->', the whole thing is the conclusion
                    conclusion = goal_full
                
                # Also handle 'let ... in' constructs
                # If conclusion starts with 'let', we want what comes after 'in'
                while conclusion.strip().startswith('let '):
                    # Find the matching 'in'
                    in_pos = conclusion.find(' in ')
                    if in_pos != -1:
                        conclusion = conclusion[in_pos + 4:].strip()
                    else:
                        break
                
                return (conclusion, hyps_str)
            elif isinstance(goal, str):
                return (goal.strip(), "")
            else:
                return (str(goal).strip(), "")
        
        # Create the branching node
        branching_node = ProofTreeNode(
            tactic=tactic,
            goals_before=goals_before,
            goals_after=goals_after,
            hypotheses_before=hypotheses_before,
            hypotheses_after=hypotheses_after,
            step_number=step_number,
            parent=parent_subgoal
        )
        
        parent_subgoal.children.append(branching_node)
        self.open_subgoals.remove(parent_subgoal)
        
        # Create child nodes for each new subgoal
        new_subgoal_nodes = []
        for i, subgoal in enumerate(subgoals):
            goal_conclusion, hyps_str = extract_goal_conclusion(subgoal)
            
            self.logger.debug(f"Subgoal {i+1}/{len(subgoals)}:")
            self.logger.debug(f"  Conclusion: {goal_conclusion[:100]}{'...' if len(goal_conclusion) > 100 else ''}")
            hyp_count = len(hyps_str.split('\n')) if hyps_str else 0
            self.logger.debug(f"  Hyps: {hyp_count} hypotheses")
            
            subgoal_node = ProofTreeNode(
                tactic=f"[Subgoal {i+1}/{len(subgoals)}]",
                goals_before=goal_conclusion,
                goals_after=goal_conclusion,
                hypotheses_before=hyps_str,
                hypotheses_after=hyps_str,
                step_number=step_number,
                parent=branching_node,
                status="Open"
            )
            branching_node.children.append(subgoal_node)
            new_subgoal_nodes.append(subgoal_node)
        
        self.open_subgoals.extend(new_subgoal_nodes)
        
        for i, node in enumerate(self.open_subgoals):
            if not isinstance(node, ProofTreeNode):
                self.logger.error(f"❌ open_subgoals[{i}] is not a ProofTreeNode! Type: {type(node)}")
                raise TypeError(f"Expected ProofTreeNode but got {type(node)}")
        
        self.logger.info(f"Created {len(new_subgoal_nodes)} new subgoal nodes. Total open: {len(self.open_subgoals)}")
        
        return branching_node

    # version works well
    def attach_to_correct_subgoal(
        self,
        tactic: str,
        goals_before: str,
        goals_after: str,
        hypotheses_before: str,
        hypotheses_after: str,
        step_number: int,
        subgoals_before: list,
        subgoals_after: list
    ) -> Optional['ProofTreeNode']:
        """
        Attach a tactic node to the correct open subgoal by comparing subgoal lists.
        Follows Coq's convention: work on subgoals in order (first subgoal first).
        """
        if not self.open_subgoals:
            self.logger.warning("No open subgoals to attach to")
            return None
        
        # IN COQ, WE ALWAYS WORK ON THE FIRST OPEN SUBGOAL
        target_subgoal = self.open_subgoals[0]
        
        # VERIFY target_subgoal is a ProofTreeNode
        if not isinstance(target_subgoal, ProofTreeNode):
            self.logger.error(f"❌ Target subgoal is not a ProofTreeNode! Type: {type(target_subgoal)}")
            self.logger.error(f"❌ Content: {target_subgoal}")
            self.logger.error(f"❌ Full open_subgoals list:")
            for i, item in enumerate(self.open_subgoals):
                self.logger.error(f"   [{i}] Type: {type(item)}, Content: {item}")
            raise TypeError(f"Expected ProofTreeNode but got {type(target_subgoal)}")
        
        self.logger.info(f"Attaching tactic to first open subgoal (index 0, total open: {len(self.open_subgoals)})")
        
        # Create and attach the new node
        new_node = ProofTreeNode(
            tactic=tactic,
            goals_before=goals_before,
            goals_after=goals_after,
            hypotheses_before=hypotheses_before,
            hypotheses_after=hypotheses_after,
            step_number=step_number,
            parent=target_subgoal
        )
        
        target_subgoal.children.append(new_node)
        
        # Update open subgoals list based on what happened
        if len(subgoals_after) == 0:
            # First subgoal was completed - remove it
            self.open_subgoals.pop(0)
            self.logger.info(f"First subgoal completed. {len(self.open_subgoals)} open subgoals remaining")
        elif len(subgoals_after) < len(subgoals_before):
            # First subgoal was completed - remove it
            self.open_subgoals.pop(0)
            self.logger.info(f"First subgoal completed. {len(self.open_subgoals)} open subgoals remaining")
        else:
            # First subgoal was transformed but not completed
            # Replace the old open subgoal with the new node
            self.open_subgoals[0] = new_node
            self.logger.info(f"First subgoal transformed, updated open subgoals list")
        
        # VERIFY all items in open_subgoals are ProofTreeNode objects after update
        for i, node in enumerate(self.open_subgoals):
            if not isinstance(node, ProofTreeNode):
                self.logger.error(f"❌ open_subgoals[{i}] is not a ProofTreeNode after update! Type: {type(node)}")
                raise TypeError(f"Expected ProofTreeNode but got {type(node)}")
        
        return new_node

    def delete_subtree_by_step_number(self, target_step_number: int) -> Dict[str, Any]:
        """
        Delete all nodes with step_number >= target_step_number.
        Rebuild open_subgoals by finding all leaf nodes with step_number < target_step_number.
        
        Args:
            target_step_number: Step number to roll back to (exclusive)
        
        Returns:
            Dictionary with rollback information
        """
        if not self.root:
            self.logger.warning("No proof tree to delete from")
            return {"deleted_count": 0, "open_subgoals_updated": False}
        
        deleted_count = 0
        
        def delete_from_node(node: 'ProofTreeNode') -> bool:
            """
            Recursively delete children with step_number >= target_step_number.
            Returns True if this node should be kept, False if it should be deleted.
            """
            nonlocal deleted_count
            
            # If this node should be deleted, return False
            if node.step_number > target_step_number:
                deleted_count += 1
                return False
            
            # Keep this node, but check its children
            node.children = [
                child for child in node.children
                if delete_from_node(child)
            ]
            
            return True
        
        # Start deletion from root's children
        self.root.children = [
            child for child in self.root.children
            if delete_from_node(child)
        ]
        
        # CRITICAL: Rebuild open_subgoals by finding all leaf nodes
        # A leaf node represents an open subgoal that needs work
        def find_leaf_nodes(node: 'ProofTreeNode', leaves: list):
            """Find all leaf nodes in the tree."""
            if not node.children:
                # This is a leaf node - it's an open subgoal
                leaves.append(node)
            else:
                # Recursively check children
                for child in node.children:
                    find_leaf_nodes(child, leaves)
        
        # Rebuild open_subgoals from leaf nodes
        old_open_count = len(self.open_subgoals)
        self.open_subgoals = []
        
        if self.root:
            find_leaf_nodes(self.root, self.open_subgoals)
        
        new_open_count = len(self.open_subgoals)
        
        # Verify all items are ProofTreeNode objects
        for i, node in enumerate(self.open_subgoals):
            if not isinstance(node, ProofTreeNode):
                self.logger.error(f"❌ open_subgoals[{i}] is not a ProofTreeNode! Type: {type(node)}")
                raise TypeError(f"Expected ProofTreeNode but got {type(node)}")
        
        self.logger.info(
            f"Deleted {deleted_count} nodes with step_number >= {target_step_number}"
        )
        self.logger.info(
            f"Rebuilt open_subgoals from leaf nodes: {old_open_count} -> {new_open_count}"
        )
        
        if new_open_count > 0:
            self.logger.info(f"Open subgoals after rollback:")
            for i, node in enumerate(self.open_subgoals):
                self.logger.info(f"  [{i}] step {node.step_number}: {node.tactic[:50]}")
        
        return {
            "deleted_count": deleted_count,
            "open_subgoals_updated": True,
            "old_open_count": old_open_count,
            "new_open_count": new_open_count
        }

    def to_dict(self) -> Dict[str, Any]:
        """Convert proof tree to dictionary for JSON serialization."""
        def node_to_dict(node: 'ProofTreeNode') -> Dict[str, Any]:
            return {
                'tactic': node.tactic,
                'step_number': node.step_number,
                'goals_before': node.goals_before,
                'goals_after': node.goals_after,
                'hypotheses_before': node.hypotheses_before,
                'hypotheses_after': node.hypotheses_after,
                'status': node.status,
                'subgoal_index': node.subgoal_index,
                'children': [node_to_dict(child) for child in node.children]
            }
        
        return {
            'root': node_to_dict(self.root) if self.root else None,
            'metadata': {
                'open_subgoals_count': len(self.open_subgoals),
                'active_subgoal': self.open_subgoals[0].tactic if self.open_subgoals else None,  # Fixed: access .tactic instead of [1]
            }
        }

    def save_to_json(self, filepath: str, prefix: str = ""):
        from pathlib import Path
        path = Path(filepath)
        # If path is not absolute, resolve to current working directory
        if not path.is_absolute():
            path = Path.cwd() / path
        new_filepath = str(path.parent / (prefix + path.name))
        with open(new_filepath, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=2, ensure_ascii=False)
    
    def save_to_png(self, filepath: str, prefix: str = ""):
        from pathlib import Path
        
        dot = Digraph(comment="Proof Tree", format="png")
        if not self.root:
            return

        def add_nodes_edges(node, parent_id=None):
            node_id = f"step_{node.step_number}_{id(node)}"
            
            if node.is_subgoal_node():
                # Subgoal intermediate node
                label = f"subgoal {node.subgoal_index}"
                color = "lightblue" if node.status == "Active" else "lightgreen" if node.status == "Proved" else "lightgray"
                dot.node(node_id, label, style="filled", fillcolor=color, shape="box")
            else:
                # Tactic node
                label = f"{node.step_number}: {node.tactic.strip()}"
                if node.status:
                    label += f" [{node.status.upper()}]"
                
                color = "yellow" if node.status == "Active" else "lightgreen" if node.status == "Proved" else "white"
                dot.node(node_id, label, style="filled", fillcolor=color)
            
            if parent_id:
                dot.edge(parent_id, node_id)
                
            for child in node.children:
                add_nodes_edges(child, node_id)

        add_nodes_edges(self.root)
        
        # Convert filepath to Path object
        path = Path(filepath)
        
        # If path is not absolute, resolve to current working directory
        if not path.is_absolute():
            path = Path.cwd() / path
        
        # Add prefix to filename
        new_filepath = str(path.parent / (prefix + path.name))
        
        # Render the graph
        dot.render(new_filepath, view=False, cleanup=True)

    def get_proof_tree_string(self) -> str:
        """
        Returns a string representation of the proof tree.
        For ALL open leaf nodes (including root), show the current goal and hypotheses.
        """
        if not self.root:
            return "Proof tree is empty."
    
        lines = []
        lines.append("\n*************Start Proof Tree*****************\n")
    
        def extract_focused_goal(goals_text: str) -> str:
            """
            Extract only the focused goal (first section before 'Stack:' marker).
            Removes 'Stack:' section and everything after it.
            Also removes 'Goals:' prefix and 'Bullet:' suffix.
            """
            if not goals_text:
                return ""
            
            # Remove "Goals:" prefix if present
            text = goals_text.strip()
            if text.startswith("Goals:"):
                text = text[6:].strip()
            
            # Remove "Bullet: None" or similar at the end
            if '\nBullet:' in text:
                text = text.split('\nBullet:')[0].strip()
            elif 'Bullet:' in text:
                text = text.split('Bullet:')[0].strip()
            
            # Most importantly: Remove "Stack:" and everything after it
            # This is the key separator between focused goal and background goals
            if '\nStack:' in text:
                text = text.split('\nStack:')[0].strip()
            elif 'Stack:' in text:
                text = text.split('Stack:')[0].strip()
            
            # Now split by the dash separator pattern (look for lines of dashes)
            # Use regex to find separator lines (10 or more consecutive dashes)
            import re
            parts = re.split(r'\n-{10,}\n', text)
            
            if len(parts) >= 2:
                # Take the part between the first and second separator
                # Format is: [empty/whitespace] --- [goal content] --- [other stuff]
                # We want the middle part
                focused_section = parts[1].strip() if len(parts) > 1 else parts[0].strip()
            else:
                # No proper separators found, just use the whole text
                focused_section = text.strip()
            
            return focused_section
    
        def recurse(node, indent=""):
            is_leaf = len(node.children) == 0
            
            if node.is_subgoal_node():
                label = f"subgoal {node.subgoal_index}"
                if node.status:
                    label += f" [{node.status.upper()}]"
                lines.append(f"{indent}{label}")
                
                # For open leaf subgoals, show goal
                if is_leaf and node.status != "Proved":
                    if node.goals_after.strip():
                        lines.append(f"{indent}  {node.goals_after.strip()}")
            else:
                # Tactic node
                label = f"{node.step_number}: {node.tactic.strip()}"
                if node.status:
                    label += f" [{node.status.upper()}]"
                lines.append(f"{indent}{label}")
                
                # For ALL open leaf tactics, show the focused goal
                if is_leaf and node.status != "Proved":
                    goals_text = node.goals_after.strip()
                    
                    if goals_text:
                        focused_goal = extract_focused_goal(goals_text)
                        
                        if focused_goal:
                            lines.append(f"{indent}  Goals:")
                            lines.append(f"{indent}  ")
                            #lines.append(f"{indent}  {'-' * 50}")
                            for line in focused_goal.split('\n'):
                                lines.append(f"{indent}  {line}")
                            #lines.append(f"{indent}  {'-' * 50}")
                        else:
                            # Debug: extraction failed but we have goals_text
                            self.logger.warning(f"Could not extract focused goal from node {node.step_number}")
                            self.logger.warning(f"goals_text length: {len(goals_text)}")
                            self.logger.warning(f"goals_text preview: {goals_text[:200]}")
                            # Fallback: show raw goals_text
                            lines.append(f"{indent}  Goals (raw):")
                            lines.append(f"{indent}  {goals_text}")
                    else:
                        # Debug: no goals_after at all
                        self.logger.warning(f"Node {node.step_number} ('{node.tactic}') has empty goals_after")
            
            for child in node.children:
                recurse(child, indent + "  ")
    
        recurse(self.root, "")
        lines.append("\n*************End Proof Tree*****************\n")
        
        return "\n".join(lines)


    def render(self) -> str:
        """
        Return an indented text representation of the proof tree.

        Each node is labelled with its tactic and a status annotation drawn
        from the set {open, solved, failed}.  Satisfies T-2.1 and FR-2.2.
        """
        if not self.root:
            return "Proof tree is empty."

        lines = []

        def _walk(node: "ProofTreeNode", indent: str = "") -> None:
            label = node.tactic.strip() if not node.is_subgoal_node() else node.tactic
            lines.append(f"{indent}{label}  [{node.status}]")
            for child in node.children:
                _walk(child, indent + "  ")

        _walk(self.root)
        return "\n".join(lines)

    def save_debug_png(self, step_number: int, tactic: str, out_dir: str = ".", prefix: str = ""):
        """
        Save a PNG of the current proof tree for debugging after each tactic.
        Leaf nodes (tactic or subgoal) will display the goal AND hypotheses that remain to be proved,
        unless the node is proved, in which case the goal is hidden.
        The filename will be step-{step_number}-{tactic}.png
        """
        from pathlib import Path
        import re
    
        dot = Digraph(comment="Proof Tree", format="png")
        if not self.root:
            return
    
        def sanitize(s):
            return re.sub(r'[^a-zA-Z0-9_\-]', '_', s)[:40]
    
        def add_nodes_edges(node, parent_id=None):
            node_id = f"step_{node.step_number}_{id(node)}"
            is_leaf = len(node.children) == 0
    
            # Prepare label
            if node.is_subgoal_node():
                label = f"subgoal {node.subgoal_index}"
                # For open leaf subgoals, include hypotheses AND goal
                if is_leaf and node.status != "Proved":
                    # Add hypotheses if available
                    if node.hypotheses_after.strip():
                        label += f"\nHYPOTHESES:\n{node.hypotheses_after.strip()[:200]}"
                    # Add goal
                    if node.goals_after.strip():
                        label += f"\nGOAL:\n{node.goals_after.strip()[:120]}"
                color = "lightblue" if node.status == "Active" else "lightgreen" if node.status == "Proved" else "lightgray"
                dot.node(node_id, label, style="filled", fillcolor=color, shape="box")
            else:
                label = f"{node.step_number}: {node.tactic.strip()}"
                if node.status:
                    label += f" [{node.status.upper()}]"
                # For open leaf tactics, show goal only (hypotheses are in parent subgoal)
                if is_leaf and node.status != "Proved" and node.goals_after.strip():
                    label += f"\nGOAL:\n{node.goals_after.strip()[:120]}"
                color = "yellow" if node.status == "Active" else "lightgreen" if node.status == "Proved" else "white"
                dot.node(node_id, label, style="filled", fillcolor=color)
    
            if parent_id:
                dot.edge(parent_id, node_id)
    
            for child in node.children:
                add_nodes_edges(child, node_id)
    
        add_nodes_edges(self.root)
    
        safe_tactic = sanitize(tactic)
        out_path = Path(out_dir)
        out_path.mkdir(parents=True, exist_ok=True)
        filename = f"{prefix}step-{step_number}-{safe_tactic}"
        full_path = out_path / filename
        dot.render(str(full_path), view=False, cleanup=True)
        
        return str(full_path) + ".png"

class ProofState:
    """
    Represents the proof state at a given step of the proving process.
    """
    def __init__(
        self,
        step_idx: int,
        current_goal: str,
        hypothesis: List[str],
        applied_tactics: Optional[List[str]] = None,
        reward: float = 0.0,
        parent: Optional['ProofState'] = None,
        timestamp: Optional[str] = None,
        last_tactic: str = "",
        error_info: Optional[Dict] = None
    ):
        self.step_idx = step_idx  # Number of tactics applied so far
        self.current_goal = current_goal  # The current goal as a string (or object)
        self.hypothesis = hypothesis  # The hypotheses/context at this step
        self.applied_tactics = applied_tactics or []  # Tactics so far
        self.reward = reward  # Reward for MCTS/search
        self.parent = parent  # Previous ProofState, for rollback/tree search
        self.timestamp = timestamp or datetime.now().isoformat()
        self.last_tactic = last_tactic
        self.error_info = error_info or {}
        self.logger = setup_logger("ProofState")

    def is_terminal(self) -> bool:
        """Return True if the goal is solved (empty or Qed), False otherwise."""
        return self.current_goal.strip() in {"Qed.", ""}

    def copy(self):
        """Return a deep copy of the state (useful for MCTS rollouts)."""
        return ProofState(
            self.step_idx,
            self.current_goal,
            list(self.hypothesis),
            list(self.applied_tactics),
            self.reward,
            self.parent,
            self.timestamp,
            self.last_tactic,
            dict(self.error_info)
        )

    def __str__(self):
        # Pretty-print the proof state
        return (
            f"--- ProofState at step {self.step_idx} ---\n"
            f"Current Goal:\n{self.current_goal}\n"
            f"Hypotheses: {self.hypothesis}\n"
            f"Applied Tactics: {self.applied_tactics}\n"
            f"Reward: {self.reward}\n"
            f"Timestamp: {self.timestamp}\n"
            "----------------------------------------"
        )

    def pretty_print(self):
        self.logger.info(self.__str__())

