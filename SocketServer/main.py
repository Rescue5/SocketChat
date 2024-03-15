import asyncio
import os
import uuid
import ssl
import logging
import time
from typing import Dict
from pydantic import BaseModel, ValidationError, field_validator
from dotenv import load_dotenv


load_dotenv('req.env')
HOST = os.getenv('HOST')
PORT = os.getenv('PORT')
PASSWORD = os.getenv('PASSWORD')
CRT_PATH = os.getenv('CRT_PATH')
KEY_PATH = os.getenv('KEY_PATH')


class ClientSendRequest(BaseModel):
    message: str
    split_message: list
    split_message_len: int

    @field_validator('split_message_len')
    @classmethod
    def check_split_message_len(cls, value):
        if value == 1:
            raise SendRequestError()
        if value < 1:
            raise ClientRequestError()
        else:
            return value


class ClientSendToRequest(BaseModel):
    message: str
    split_message: list

    @field_validator('split_message')
    @classmethod
    def check_split_message(cls, value):
        if len(value) == 2:
            raise SendRequestError()
        elif len(value) == 1:
            raise SendRequestError('Sendto requires UUID')
        elif len(value) < 1:
            raise ClientRequestError()
        elif len(value[1]) != 36:
            raise SendRequestError('Incorrect UUID')
        else:
            return value


logging.basicConfig(level=logging.INFO, filename='server.log',
                    format="%(levelname)s - %(asctime)s - %(lineno)d - %(message)s")
logger = logging.getLogger('server')
open('server.log', 'w').close()
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
    split_message = message.split()
    split_message_len = len(split_message)
    validation = ClientSendRequest(message=message, split_message=split_message, split_message_len=split_message_len)
    response = f"{' '.join(validation.split_message[1:])} \n".encode('utf-8')
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
    split_message = message.split()
    validation = ClientSendToRequest(message=message, split_message=split_message)
    response = f"{' '.join(validation.split_message[2:])} \n".encode('utf-8')
    client_dict[split_message[1]].write(response)
    await client_dict[split_message[1]].drain()



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
        if not message:
            raise ClientRequestError()

        request_check = message.split()[0]
        if request_check == 'send':
            await send_all(message, session_id)
        elif request_check == 'sendto':
            await send_to_client(message)
        elif request_check == 'disconnect':
            raise asyncio.CancelledError()
        elif request_check == 'show_client':
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
    client_ip = 'unknown'
    client_port = 'unknown'
    session_id = 'unknown'
    writer.write('waiting for password\n'.encode())
    if await check_password(reader):
        writer.write('authenticated\n'.encode())
    else:
        writer.write("Password incorrect or timeout, you are being disconnected.\n".encode())
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    logger.info('client authenticated')
    try:
        client_info = writer.get_extra_info('peername')
        client_info_str = ' - '.join(map(str, client_info))
        logger.info(f'client info: {client_info_str}')
        if len(client_info) == 2:  # IPv4
            client_ip, client_port = client_info
        elif len(client_info) == 4:  # IPv6
            client_ip, client_port, _, _ = client_info
        session_id = str(uuid.uuid4())
        client_dict[session_id] = writer
        logger.info(f'Connected from {client_ip}:{client_port}')
    except Exception as e:
        logger.error(f'Error getting client ip and port: {e}')
        writer.close()
        await writer.wait_closed()
    try:
        while True:
            data = await reader.read(1024)
            if data.strip() == b'':
                continue
            message = data.decode()
            logger.info(f"Received request: {message} from {client_ip}:{client_port}")
            await handle_client_message(message, session_id, writer, client_ip, client_port)
    except ClientRequestError as cre:
        logger.error(cre)
        error_message = f'Error: {str(cre)}\n'
        writer.write(error_message.encode())
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
    except KeyboardInterrupt:
        raise


async def main():
    """
    Main function to start the asyncio server.

    This function sets up and starts an asyncio-based server on a specified hostname and port, logging server start and
    runtime duration.

    No explicit return value but initializes and runs the server indefinitely until manually stopped or an unhandled
    exception occurs.
    """
    start_time = time.time()
    ssl_context = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
    ssl_context.load_cert_chain(certfile=CRT_PATH, keyfile=KEY_PATH)
    server = await asyncio.start_server(client_connected_cb, HOST, PORT, reuse_address=True,
                                        reuse_port=True, ssl=ssl_context)
    logger.info('Server started on {}:{}'.format(HOST, PORT))
    print('Server started on {}:{}'.format(HOST, PORT))
    try:
        await server.serve_forever()
    except KeyboardInterrupt:
        logger.info('Server stopped by user')
    finally:
        tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        server.close()
        await server.wait_closed()
        logger.info(f"Server was running for {round(time.time() - start_time)} seconds")


async def main_wrapper():
    try:
        await main()
    except Exception as e:
        logging.error(f"Unhandled exception: {e}", exc_info=True)
        raise


if __name__ == '__main__':
    asyncio.run(main_wrapper())
