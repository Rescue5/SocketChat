from pydantic import BaseModel, field_validator
from typing import Dict
import asyncio
from exceptions import ClientRequestError, SendRequestError


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


async def send_all(message: str, session_id: str, client_dict: Dict[str, asyncio.StreamWriter]) -> None:
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


async def send_to_client(message: str, client_dict: Dict[str, asyncio.StreamWriter]) -> None:
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


async def show_client(writer: asyncio.StreamWriter, client_dict: Dict[str, asyncio.StreamWriter]) -> None:
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


async def info(writer: asyncio.StreamWriter):
    """
    Sends a list of available requests to the requester.

    Args:
        writer (asyncio.StreamWriter): The StreamWriter object associated with the client requesting the list of
        connected clients.

    This function generates no return value but sends data directly to the client through the provided StreamWriter.
    """
    writer.write('Available request:\n'
                 'show_client - list of currently connected client\n'
                 'send <message> - Broadcasts a message to all connected clients\n'
                 'sendto <UUID> <message> - Sends a message to a specific client\n'
                 'disconnect - disconnect you from server\n'.encode())
    await writer.drain()
