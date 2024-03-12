import asyncio
import uuid
import logging
import time
from typing import Dict
from pydantic import BaseModel, ValidationError

HOST = 'localhost'
PORT = 5500


class ClientMessage(BaseModel):
    message: str

class ServerMessage(BaseModel):
    message: str


PASSWORD = '112233'
logging.basicConfig(level=logging.INFO, filename='server.log', format="%(levelname)s - %(asctime)s - %(lineno)d - %(message)s")
logger = logging.getLogger('server')
client_dict: Dict[str, asyncio.StreamWriter] = {}


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


async def check_password(reader: asyncio.StreamReader, timeout: int = 30) -> bool:
    """
    Waits for a password to be sent by the client within a given timeout period.

    Args:
        reader (asyncio.StreamReader): The StreamReader object associated with the client connection, used to read
            data sent by the client.
        timeout (int, optional): The maximum amount of time in seconds to wait for the client to send the password.
            Defaults to 30 seconds.

    Returns:
        bool: True if the correct password was received within the timeout period, False otherwise.

    Raises:
        asyncio.TimeoutError: If no data is received within the given timeout period.
    """
    try:
        data = await asyncio.wait_for(reader.read(100), timeout)
    except asyncio.TimeoutError:
        return False
    received_password = data.decode().strip()
    return received_password == PASSWORD


async def send_all(message: str, session_id: str) -> None:
    """
    Broadcasts a message to all connected clients except the sender.

    Args:
        message (str): The message to be sent, expected to follow the format "send <message>".
        session_id (str): The session ID of the client sending the message, to exclude them from the recipients.

    Raises:
        SendRequestError: If the message is improperly formatted (e.g., message content is missing).
    """
    if len(message.split(' ')) == 1:
        raise SendRequestError()
    response = message.split(' ')[1:]
    response = ' '.join(response)
    response = response.encode()
    for i in client_dict:
        if i != session_id:
            client_dict[i].write(response)
            await client_dict[i].drain()


async def send_to_client(message: str) -> None:
    """
    Sends a message to a specific client identified by their session ID.

    Args:
        message (str): The message string to be sent, expected to follow the format "sendto <uuid> <message>".

    Raises:
        SendRequestError: If the message is improperly formatted, the specified session ID is not found, or the message
        content is missing.
    """
    if len(message.split(' ')) == 1:
        raise SendRequestError('Not enough arguments')
    elif len(message.split(' ')) == 2:
        raise SendRequestError('')
    elif message.split(' ')[1] in client_dict:
        response = message.split(' ')[2:]
        response = ' '.join(response)
        response = response.encode()
        client_dict[message.split(' ')[1]].write(response)
        await client_dict[message.split(' ')[1]].drain()
    else:
        raise SendRequestError('Incorrect UUID')


async def show_client(writer: asyncio.StreamWriter) -> None:
    """
    Sends a list of currently connected client IDs to the requester.

    Args:
        writer (asyncio.StreamWriter): The StreamWriter object associated with the client requesting the list of
        connected clients.

    This function generates no return value but sends data directly to the client through the provided StreamWriter.
    """
    for i in client_dict:
        writer.write(f'{str(i)}\n'.encode())
        await writer.drain()


async def handle_client_message(message: str, session_id: str, writer: asyncio.StreamWriter, client_ip,
                                client_port) -> None:
    try:
        if len(message) == 0:
            raise ClientRequestError()

        request_check = message.split()[0]
        if request_check == 'send':
            await send_all(message, session_id)
        if request_check == 'sendto':
            await send_to_client(message)
        if request_check == 'disconnect':
            raise asyncio.CancelledError()
        if request_check == 'show_client':
            await show_client(writer)
        else:
            raise ClientRequestError('Unknown request type')
    except ClientRequestError as cre:
        logger.error(cre)
        error_message = f'Error: {str(cre)}\n'
        writer.write(error_message.encode())
        await writer.drain()
    except SendRequestError as sre:
        logger.error(sre)
        error_message = f'Error: {str(sre)}\n'
        writer.write(error_message.encode())
        await writer.drain()
    except asyncio.CancelledError:
        writer.close()
        await writer.wait_closed()
        del client_dict[client_port]


async def client_connected_cb(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    """
    This function serves as a callback that is called when a client connects to the server. It manages the lifecycle of
    the connection, including reading requests from the client, handling different types of requests ('send', 'sendto',
    'disconnect', 'show_client'), and closing the connection properly when needed.

    The function supports broadcasting messages to all clients, sending messages to specific clients, and providing a
    list of connected clients. It uses a global dictionary `client_dict` to keep track of connected clients and their
    sessions. Each client is assigned a unique session ID upon connection.

    Args:
        reader (asyncio.StreamReader): An object for reading data from the connection, allowing the server to receive
            messages from the client.
        writer (asyncio.StreamWriter): An object for writing data to the connection, enabling the server to send
            messages back to the client.

    Returns:
        None: This function does not return any value.

    Raises:
        ClientRequestError: If an error occurs while processing the client's request.
        SendRequestError: If an error occurs during the process of sending a message to a client or broadcasting.
        asyncio.CancelledError: If a 'disconnect' request is received, indicating the client wants to close the
            connection.

    Note:
        - The `client_dict` global variable must be defined outside this function, mapping session IDs to their
            respective StreamWriter objects.
        - Logging is performed for connection events, received messages, and errors to aid in debugging and monitoring
            the server's operation.
    """
    writer.write('waiting for password\n'.encode())
    if await check_password(reader):
        writer.write('authenticated\n'.encode())
    else:
        writer.write("Password incorrect or timeout, you are being disconnected.\n".encode())
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    global client_dict
    client_ip, client_port = writer.get_extra_info('peername')
    session_id = str(uuid.uuid4())
    client_dict[session_id] = writer
    logger.info(f'Connected from {client_ip}:{client_port}')
    try:
        while True:
            data = await reader.read(1024)
            message = data.decode()
            client_message = ClientMessage(message=message)
            logger.info(f"Received request: {message} from {client_ip}:{client_port}")
            await handle_client_message(client_message.message, session_id, writer, client_ip, client_port)
    except ValidationError:
        logger.error('Unvalidated request')
        writer.write('Client message must be str'.encode())
    except asyncio.CancelledError:
        logger.info(f'Connection closed from {client_ip}:{client_port}')
        writer.write('Connection closed.'.encode())
        await writer.drain()
        writer.close()
        await writer.wait_closed()
        del client_dict[session_id]


async def main():
    """
    Main function to start the asyncio server.

    This function sets up and starts an asyncio-based server on a specified hostname and port, logging server start and
    runtime duration.

    No explicit return value but initializes and runs the server indefinitely until manually stopped or an unhandled
    exception occurs.
    """
    start_time = time.time()
    server = await asyncio.start_server(client_connected_cb, HOST, PORT, reuse_address=True,
                                        reuse_port=True)
    logger.info('Server started')
    await server.serve_forever()
    elapsed_time = time.time() - start_time
    logger.info(f"Server was running for {elapsed_time} seconds")


if __name__ == '__main__':
    asyncio.run(main())
