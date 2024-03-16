class SendRequestError(Exception):
    """
    Exception raised when there is an issue with sending a request.

    This can occur if the message content is blank or improperly formatted for the intended send operation.

    Attributes:
        message (str): Explanation of the error. Default is 'Message content cannot be blank'.
    """

    def __init__(self, message='Message content cannot be blank'):
        self.message = message
        super().__init__(self.message)


class ClientRequestError(Exception):
    """
    Exception raised when there is an issue with the client's request.

    This may happen if the request from the client is blank or does not adhere to expected formats.

    Attributes:
        message (str): Explanation of the error. Default is 'Request cannot be blank'.
    """

    def __init__(self, message='Request cannot be blank'):
        self.message = message
        super().__init__(self.message)


class ClientCloseConnection(Exception):
    def __init__(self, message='Client close connection'):
        self.message = message
        super().__init__(self.message)