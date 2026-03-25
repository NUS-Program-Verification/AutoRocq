from coqpyt.lsp import structs
from coqpyt.lsp.endpoint import LspEndpoint


class LspClient(object):
    def __init__(self, lsp_endpoint: LspEndpoint):
        """
        Constructs a new LspClient instance.

        :param lsp_endpoint: TODO
        """
        self.lsp_endpoint = lsp_endpoint

    def initialize(
        self,
        processId,
        rootPath,
        rootUri,
        initializationOptions,
        capabilities,
        trace,
        workspaceFolders,
    ):
        """
        The initialize request is sent as the first request from the client to the server. If the server receives a request or notification
        before the initialize request it should act as follows:

        1. For a request the response should be an error with code: -32002. The message can be picked by the server.
        2. Notifications should be dropped, except for the exit notification. This will allow the exit of a server without an initialize request.

        Until the server has responded to the initialize request with an InitializeResult, the client must not send any additional requests or
        notifications to the server. In addition the server is not allowed to send any requests or notifications to the client until it has responded
        with an InitializeResult, with the exception that during the initialize request the server is allowed to send the notifications window/showMessage,
        window/logMessage and telemetry/event as well as the window/showMessageRequest request to the client.

        The initialize request may only be sent once.

        :param int processId: The process Id of the parent process that started the server. Is null if the process has not been started by another process.
                                If the parent process is not alive then the server should exit (see exit notification) its process.
        :param str rootPath: The rootPath of the workspace. Is null if no folder is open. Deprecated in favour of rootUri.
        :param DocumentUri rootUri: The rootUri of the workspace. Is null if no folder is open. If both `rootPath` and `rootUri` are set
                                    `rootUri` wins.
        :param any initializationOptions: User provided initialization options.
        :param ClientCapabilities capabilities: The capabilities provided by the client (editor or tool).
        :param Trace trace: The initial trace setting. If omitted trace is disabled ('off').
        :param list workspaceFolders: The workspace folders configured in the client when the server starts. This property is only available if the client supports workspace folders.
                                        It can be `null` if the client supports workspace folders but none are configured.
        """
        self.lsp_endpoint.start()
        return self.lsp_endpoint.call_method(
            "initialize",
            processId=processId,
            rootPath=rootPath,
            rootUri=rootUri,
            initializationOptions=initializationOptions,
            capabilities=capabilities,
            trace=trace,
            workspaceFolders=workspaceFolders,
        )

    def initialized(self):
        """
        The initialized notification is sent from the client to the server after the client received the result of the initialize request
        but before the client is sending any other request or notification to the server. The server can use the initialized notification
        for example to dynamically register capabilities. The initialized notification may only be sent once.
        """
        self.lsp_endpoint.send_notification("initialized")

    def shutdown(self):
        """
        The initialized notification is sent from the client to the server after the client received the result of the initialize request
        but before the client is sending any other request or notification to the server. The server can use the initialized notification
        for example to dynamically register capabilities. The initialized notification may only be sent once.
        """
        self.lsp_endpoint.stop()
        return self.lsp_endpoint.call_method("shutdown")

    def exit(self):
        """
        The initialized notification is sent from the client to the server after the client received the result of the initialize request
        but before the client is sending any other request or notification to the server. The server can use the initialized notification
        for example to dynamically register capabilities. The initialized notification may only be sent once.
        """
        self.lsp_endpoint.send_notification("exit")

    def didClose(self, textDocument: structs.TextDocumentIdentifier):
        return self.lsp_endpoint.send_notification(
            "textDocument/didClose", textDocument=textDocument
        )

    def didOpen(self, textDocument):
        """
        The document open notification is sent from the client to the server to signal newly opened text documents. The document's truth is
        now managed by the client and the server must not try to read the document's truth using the document's uri. Open in this sense
        means it is managed by the client. It doesn't necessarily mean that its content is presented in an editor. An open notification must
        not be sent more than once without a corresponding close notification send before. This means open and close notification must be
        balanced and the max open count for a particular textDocument is one. Note that a server's ability to fulfill requests is independent
        of whether a text document is open or closed.

        The DidOpenTextDocumentParams contain the language id the document is associated with. If the language Id of a document changes, the
        client needs to send a textDocument/didClose to the server followed by a textDocument/didOpen with the new language id if the server
        handles the new language id as well.

        :param TextDocumentItem textDocument: The document that was opened.
        """
        return self.lsp_endpoint.send_notification(
            "textDocument/didOpen", textDocument=textDocument
        )

    def didChange(self, textDocument, contentChanges):
        """
        The document change notification is sent from the client to the server to signal changes to a text document.
        In 2.0 the shape of the params has changed to include proper version numbers and language ids.

        :param VersionedTextDocumentIdentifier textDocument: The initial trace setting. If omitted trace is disabled ('off').
        :param TextDocumentContentChangeEvent[] contentChanges: The actual content changes. The content changes describe single state changes
            to the document. So if there are two content changes c1 and c2 for a document in state S then c1 move the document
            to S' and c2 to S''.
        """
        return self.lsp_endpoint.send_notification(
            "textDocument/didChange",
            textDocument=textDocument,
            contentChanges=contentChanges,
        )

    def documentSymbol(self, textDocument):
        """
        The document symbol request is sent from the client to the server to return a flat list of all symbols found in a given text document.
        Neither the symbol's location range nor the symbol's container name should be used to infer a hierarchy.

        :param TextDocumentItem textDocument: The text document.
        """
        result_dict = self.lsp_endpoint.call_method(
            "textDocument/documentSymbol", textDocument=textDocument
        )
        return [structs.SymbolInformation(**sym) for sym in result_dict]

    def definition(self, textDocument, position):
        """
        The goto definition request is sent from the client to the server to resolve the definition location of a symbol at a given text document position.

        :param TextDocumentItem textDocument: The text document.
        :param Position position: The position inside the text document.
        """
        result_dict = self.lsp_endpoint.call_method(
            "textDocument/definition", textDocument=textDocument, position=position
        )
        return [structs.Location(**l) for l in result_dict]

    def typeDefinition(self, textDocument, position):
        """
        The goto type definition request is sent from the client to the server to resolve the type definition location of a symbol at a given text document position.

        :param TextDocumentItem textDocument: The text document.
        :param Position position: The position inside the text document.
        """
        result_dict = self.lsp_endpoint.call_method(
            "textDocument/definition", textDocument=textDocument, position=position
        )
        return [structs.Location(**l) for l in result_dict]

    def signatureHelp(self, textDocument, position):
        """
        The signature help request is sent from the client to the server to request signature information at a given cursor position.

        :param TextDocumentItem textDocument: The text document.
        :param Position position: The position inside the text document.
        """
        result_dict = self.lsp_endpoint.call_method(
            "textDocument/signatureHelp", textDocument=textDocument, position=position
        )
        return structs.SignatureHelp(**result_dict)

    def completion(self, textDocument, position, context):
        """
        The signature help request is sent from the client to the server to request signature information at a given cursor position.

        :param TextDocumentItem textDocument: The text document.
        :param Position position: The position inside the text document.
        :param CompletionContext context: The completion context. This is only available if the client specifies
                                            to send this using `ClientCapabilities.textDocument.completion.contextSupport === true`
        """
        result_dict = self.lsp_endpoint.call_method(
            "textDocument/completion",
            textDocument=textDocument,
            position=position,
            context=context,
        )
        if "isIncomplete" in result_dict:
            return structs.CompletionList(**result_dict)

        return [structs.CompletionItem(**l) for l in result_dict]

    def declaration(self, textDocument, position):
        """
        The go to declaration request is sent from the client to the server to resolve the declaration location of a
        symbol at a given text document position.

        The result type LocationLink[] got introduce with version 3.14.0 and depends in the corresponding client
        capability `clientCapabilities.textDocument.declaration.linkSupport`.

        :param TextDocumentItem textDocument: The text document.
        :param Position position: The position inside the text document.
        """
        result_dict = self.lsp_endpoint.call_method(
            "textDocument/declaration", textDocument=textDocument, position=position
        )
        if "uri" in result_dict:
            return structs.Location(**result_dict)

        return [
            structs.Location(**l) if "uri" in l else structs.LinkLocation(**l)
            for l in result_dict
        ]

    def definition(self, textDocument, position):
        """
        The go to definition request is sent from the client to the server to resolve the declaration location of a
        symbol at a given text document position.

        The result type LocationLink[] got introduce with version 3.14.0 and depends in the corresponding client
        capability `clientCapabilities.textDocument.declaration.linkSupport`.

        :param TextDocumentItem textDocument: The text document.
        :param Position position: The position inside the text document.
        """
        result_dict = self.lsp_endpoint.call_method(
            "textDocument/definition", textDocument=textDocument, position=position
        )
        if "uri" in result_dict:
            return structs.Location(**result_dict)

        return [
            structs.Location(**l) if "uri" in l else structs.LinkLocation(**l)
            for l in result_dict
        ]


# Coq-specific LSP client
import sys
import threading
import subprocess
from typing import Tuple, Dict, List, Optional
from coqpyt.lsp.structs import *
from coqpyt.lsp.json_rpc_endpoint import JsonRpcEndpoint


class CoqLspClient(LspClient):
    """Abstraction to interact with coq-lsp

    Attributes:
        file_progress (Dict[str, List[CoqFileProgressParams]]): Contains all
            the `$/coq/fileProgress` notifications sent by the server. The
            keys are the URIs of the files and the values are the list of
            notifications.
    """

    __DEFAULT_INIT_OPTIONS = {
        "max_errors": 120000000,
        "goal_after_tactic": False,
        "show_coq_info_messages": True,
    }

    def __init__(
        self,
        root_uri: str,
        timeout: int = 30,
        memory_limit: int = 2097152,
        coq_lsp: str = "coq-lsp",
        coq_lsp_options: Tuple[str] = None,
        init_options: Dict = __DEFAULT_INIT_OPTIONS,
    ):
        """Creates a CoqLspClient

        Args:
            root_uri (str): URI to the workspace where coq-lsp will run
                The URI can be either a file or a folder.
            timeout (int, optional): Timeout used for the coq-lsp operations.
                Defaults to 2.
            memory_limit (int, optional): RAM limit for the coq-lsp process
                in kbytes. It only works for Linux systems. Defaults to 2097152.
            coq_lsp(str, optional): Path to the coq-lsp binary. Defaults to "coq-lsp".
            init_options (Dict, optional): Initialization options for coq-lsp server.
                Available options are:
                    max_errors (int): Maximum number of errors per file, after that,
                        coq-lsp will stop checking the file. Defaults to 120000000.
                    show_coq_info_messages (bool): Show Coq's info messages as diagnostics.
                        Defaults to false.
                    show_notices_as_diagnostics (bool): Show Coq's notice messages
                        as diagnostics, such as `About` and `Search` operations.
                        Defaults to false.
                    debug (bool): Enable Debug in Coq Server. Defaults to false.
                    pp_type (int): Method to print Coq Terms.
                        0 = Print to string
                        1 = Use jsCoq's Pp rich layout printer
                        2 = Coq Layout Engine
                        Defaults to 1.
        """
        self.file_progress: Dict[str, List[CoqFileProgressParams]] = {}

        if sys.platform.startswith("linux"):
            command = f"ulimit -v {memory_limit}; {coq_lsp}"
        else:
            command = f"{coq_lsp}"

        if coq_lsp_options is None:
            command += " -D 0"
        else:
            hasDOption = False
            for option in coq_lsp_options:
                if option.startswith("-D"):
                    hasDOption = True
                    break
            if not hasDOption:
                command += " -D 0"
            command += " " + " ".join(coq_lsp_options)

        proc = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stdin=subprocess.PIPE,
            shell=True,
        )
        json_rpc_endpoint = JsonRpcEndpoint(proc.stdin, proc.stdout)
        lsp_endpoint = LspEndpoint(json_rpc_endpoint, timeout=timeout)
        lsp_endpoint.notify_callbacks = {
            "$/coq/fileProgress": self.__handle_file_progress,
            "textDocument/publishDiagnostics": self.__handle_publish_diagnostics,
        }
        super().__init__(lsp_endpoint)
        workspaces = [{"name": "coq-lsp", "uri": root_uri}]
        # This is required to be False since we use it to know if operations
        # such as didOpen and didChange already finished.
        init_options["eager_diagnostics"] = False
        self.initialize(
            proc.pid,
            "",
            root_uri,
            init_options,
            {},
            "off",
            workspaces,
        )
        self.initialized()
        # Used to check if didOpen and didChange already finished
        self.__completed_operation = threading.Event()

    def __handle_publish_diagnostics(self, params: Dict):
        self.__completed_operation.set()

    def __handle_file_progress(self, params: Dict):
        coqFileProgressKind = CoqFileProgressParams.parse(params)
        uri = coqFileProgressKind.textDocument.uri
        if uri not in self.file_progress:
            self.file_progress[uri] = [coqFileProgressKind]
        else:
            self.file_progress[uri].append(coqFileProgressKind)

    def __wait_for_operation(self):
        timeout = not self.__completed_operation.wait(self.lsp_endpoint.timeout)
        self.__completed_operation.clear()
        if self.lsp_endpoint.shutdown_flag:
            raise ResponseError(ErrorCodes.ServerQuit, "Server quit")
        if timeout:
            self.shutdown()
            self.exit()
            raise ResponseError(ErrorCodes.ServerTimeout, "Server timeout")

    def didOpen(self, textDocument: TextDocumentItem):
        """Open a text document in the server.

        Args:
            textDocument (TextDocumentItem): Text document to open
        """
        self.lsp_endpoint.diagnostics[textDocument.uri] = []
        super().didOpen(textDocument)
        self.__wait_for_operation()

    def didChange(
        self,
        textDocument: VersionedTextDocumentIdentifier,
        contentChanges: list[TextDocumentContentChangeEvent],
    ):
        """Submit changes on a text document already open on the server.

        Args:
            textDocument (VersionedTextDocumentIdentifier): Text document changed.
            contentChanges (list[TextDocumentContentChangeEvent]): Changes made.
        """
        self.lsp_endpoint.diagnostics[textDocument.uri] = []
        super().didChange(textDocument, contentChanges)
        self.__wait_for_operation()

    def proof_goals(
        self, textDocument: TextDocumentIdentifier, position: Position
    ) -> Optional[GoalAnswer]:
        """Get proof goals and relevant information at a position.

        Args:
            textDocument (TextDocumentIdentifier): Text document to consider.
            position (Position): Position used to get the proof goals.

        Returns:
            GoalAnswer: Contains the goals at a position, messages associated
                to the position and if errors exist, the top error at the position.
        """
        result_dict = self.lsp_endpoint.call_method(
            "proof/goals", textDocument=textDocument, position=position
        )
        return GoalAnswer.parse(result_dict)

    def get_document(
        self, textDocument: TextDocumentIdentifier
    ) -> Optional[FlecheDocument]:
        """Get the AST of a text document.

        Args:
            textDocument (TextDocumentIdentifier): Text document

        Returns:
            Optional[FlecheDocument]: Serialized version of Fleche's document
        """
        result_dict = self.lsp_endpoint.call_method(
            "coq/getDocument", textDocument=textDocument
        )
        return FlecheDocument.parse(result_dict)

    def save_vo(self, textDocument: TextDocumentIdentifier):
        """Save a compiled file to disk.

        Args:
            textDocument (TextDocumentIdentifier): File to be saved.
                The uri in the textDocument should contain an absolute path.
        """
        self.lsp_endpoint.call_method("coq/saveVo", textDocument=textDocument)
    # TODO: handle performance data notification?
