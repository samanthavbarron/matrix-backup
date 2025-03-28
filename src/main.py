import sqlalchemy
import json
import asyncio
from nio import AsyncClient, RoomMessageText
from sqlalchemy.orm import Session
import os
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def write_to_messages_table(
    session,
    message_text: RoomMessageText,
):
    logger.info(f"Writing message {message_text.source['event_id']} to the messages table.")
    fields = [
        "event_id",
        "origin_server_ts",
        "room_id",
        "sender",
        "user_id",
    ]
    data = {key: message_text.source[key] for key in fields}
    data["content"] = message_text.source["content"]["body"]
    fields = list(data.keys())

    result = session.execute(sqlalchemy.text(
        f"""
        INSERT INTO messages ({",".join(fields)})
        VALUES ({",".join([f":{key}" for key in fields])})
        """
    ), [data])
    session.commit()

def write_to_rooms_table(session, room_id: str, room_name: str, latest_event_id: str = "null"):
    logger.info(f"Writing room {room_id} to the rooms table with latest_event_id={latest_event_id}.")
    result = session.execute(sqlalchemy.text(
        """
        INSERT INTO rooms (room_id, room_name, latest_event_id)
        VALUES (:room_id, :room_name, :latest_event_id)
        ON CONFLICT (room_id) DO UPDATE
        SET room_name = EXCLUDED.room_name, latest_event_id = EXCLUDED.latest_event_id
        """
    ), [{"room_id": room_id, "room_name": room_name, "latest_event_id": latest_event_id}])
    session.commit()

async def main(
    user: str,
    homeserver: str,
    password: str,
    db_url: str,
):
    logger.info("Starting main backup process.")
    engine = sqlalchemy.create_engine(db_url)
    with Session(engine) as session:
        logger.info("Ensuring database tables exist.")
        # Create a new table for the rooms if it doesn't exist
        result = session.execute(sqlalchemy.text(
            """
            CREATE TABLE IF NOT EXISTS rooms (
                room_id TEXT PRIMARY KEY,
                room_name TEXT,
                latest_event_id TEXT
            )
            """
        ))
        session.commit()

        # Create a new table for the messages if it doesn't exist
        result = session.execute(sqlalchemy.text(
            """
            CREATE TABLE IF NOT EXISTS messages (
                event_id TEXT PRIMARY KEY,
                room_id TEXT,
                sender TEXT,
                user_id TEXT,
                content TEXT,
                origin_server_ts TIMESTAMP
            )
            """
        ))
        session.commit()
    
        client = AsyncClient(
            homeserver=homeserver,
            user=user,
            device_id="matrix_backup",
        )
        logger.info("Logging into the Matrix server.")
        await asyncio.sleep(5)
        await client.login(password)

        logger.info("Fetching joined rooms.")
        joined_rooms_response = await client.joined_rooms()
        for room_id in joined_rooms_response.rooms:
            logger.info(f"Processing room {room_id}.")
            # Write the room to the database if it doesn't exist
            room_name = "null"
            write_to_rooms_table(session, room_id, room_name)

            messages_response = await client.room_messages(
                room_id=room_id,
            )
            logger.info(f"Fetched messages for room {room_id}.")
            latest_event_id = None
            for event in messages_response.chunk:
                if isinstance(event, RoomMessageText):
                    if latest_event_id is None:
                        latest_event_id = event.source["event_id"]
                    write_to_messages_table(session, event)
            if latest_event_id is not None:
                write_to_rooms_table(session, room_id, room_name, latest_event_id=latest_event_id)


if __name__ == "__main__":
    logger.info("Starting Matrix backup script.")
    # Get the inputs from environment variables
    user = os.getenv("MATRIX_USER")
    homeserver = os.getenv("MATRIX_HOMESERVER")
    password = os.getenv("MATRIX_PASSWORD")
    db_url = os.getenv("DATABASE_URL")
    backup_interval = os.getenv("BACKUP_INTERVAL", "300")  # Default to 5 minutes if not set

    if not all([user, homeserver, password, db_url]):
        logger.error("Missing one or more required environment variables.")
        raise ValueError("Missing one or more required environment variables: MATRIX_USER, MATRIX_HOMESERVER, MATRIX_PASSWORD, DATABASE_URL")

    try:
        backup_interval = int(backup_interval)
    except ValueError:
        logger.error("BACKUP_INTERVAL must be an integer.")
        raise ValueError("BACKUP_INTERVAL must be an integer representing seconds")

    async def run_backup_loop():
        try:
            while True:
                logger.info("Running backup loop.")
                await main(user, homeserver, password, db_url)
                logger.info(f"Sleeping for {backup_interval} seconds before the next backup.")
                await asyncio.sleep(backup_interval)
        except KeyboardInterrupt:
            logger.info("Backup loop interrupted. Exiting...")

    asyncio.run(run_backup_loop())