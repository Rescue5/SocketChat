# Ошибка отключение клиента через keyboard interrupt - предположительно строка 168

import asyncio
import os
import uuid
import ssl
import logging
import time
from typing import Dict
from pydantic import ValidationError
from dotenv import load_dotenv
from client_requests import send_to_client, show_client, send_all, info
from exceptions import ClientRequestError, SendRequestError, ClientCloseConnection

load_dotenv('req.env')
HOST = os.getenv('HOST')
PORT = os.getenv('PORT')
PASSWORD = os.getenv('PASSWORD')
CRT_PATH = os.getenv('CRT_PATH')
KEY_PATH = os.getenv('KEY_PATH')

logging.basicConfig(level=logging.INFO, filename='server.log',
                    format="%(levelname)s - %(asctime)s - %(lineno)d - %(message)s")
logger = logging.getLogger('server')
open('server.log', 'w').close()
client_dict: Dict[str, asyncio.StreamWriter] = {}


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
    global client_dict
    try:
        data = await asyncio.wait_for(reader.read(100), timeout)
    except asyncio.TimeoutError:
        return False
    received_password = data.decode().strip()
    return received_password == PASSWORD


async def handle_client_message(message: str, session_id: str, writer: asyncio.StreamWriter, client_ip,
                                client_port) -> None:
    try:
        if not message:
            raise ClientRequestError()

        request_check = message.split()[0]
        if request_check == 'send':
            await send_all(message, session_id, client_dict)
        elif request_check == 'sendto':
            await send_to_client(message, client_dict)
        elif request_check == 'disconnect':
            raise asyncio.CancelledError()
        elif request_check == 'show_client':
            await show_client(writer, client_dict)
        elif request_check == 'info':
            await info(writer)
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
        writer.write('You will be disconnected'.encode())
        await writer.drain()
        del (client_dict[session_id])
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
            if not data:
                logger.info(f"Client {client_ip}:{client_port} disconnected")
                raise ClientCloseConnection()
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
    except ClientCloseConnection:
        writer.close()
        await writer.wait_closed()
    except Exception as e:
        logger.exception(e)


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
