from prover_backends.base import ProverBackend
from prover_backends.types import SearchResult


class ContextSearch:
    def __init__(self, backend: ProverBackend):
        self.backend = backend

    def search(self, query: str, goal_context: str = "") -> SearchResult:
        return self.backend.search(query, goal_context)

    def execute_query(self, query_type: str, identifier: str = None,
                      pattern: str = None, goal_context: str = "") -> SearchResult:
        return self.backend.search_by_type(query_type, identifier, pattern, goal_context)

    def search_lemma(self, lemma_name: str, goal_context: str = "") -> SearchResult:
        return self.execute_query("search", identifier=lemma_name, goal_context=goal_context)

    def search_pattern(self, pattern: str, goal_context: str = "") -> SearchResult:
        return self.execute_query("search", pattern=pattern, goal_context=goal_context)

    def print_definition(self, identifier: str) -> SearchResult:
        return self.execute_query("print", identifier)

    def print_assumptions(self, identifier: str = None) -> SearchResult:
        return self.execute_query("print_assumptions", identifier)

    def locate_definition(self, identifier: str) -> SearchResult:
        return self.execute_query("locate", identifier)

    def about_identifier(self, identifier: str) -> SearchResult:
        return self.execute_query("about", identifier)

    def check_term(self, term: str) -> SearchResult:
        return self.execute_query("check", term)
