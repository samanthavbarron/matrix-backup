import sqlalchemy
import json
import asyncio
from nio import AsyncClient, RoomMessageText
from sqlalchemy.orm import Session

def write_to_messages_table(
    session,
    message_text: RoomMessageText,
):
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
    engine = sqlalchemy.create_engine(db_url)
    with Session(engine) as session:
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
        await asyncio.sleep(5)
        await client.login(password)

        joined_rooms_response = await client.joined_rooms()
        for room_id in joined_rooms_response.rooms:
            # Write the room to the database if it doesn't exist
            room_name = "null"
            write_to_rooms_table(session, room_id, room_name)

            messages_response = await client.room_messages(
                room_id=room_id,
            )
            latest_event_id = None
            for event in messages_response.chunk:
                if isinstance(event, RoomMessageText):
                    if latest_event_id is None:
                        latest_event_id = event.source["event_id"]
                    write_to_messages_table(session, event)
            if latest_event_id is not None:
                write_to_rooms_table(session, room_id, room_name, latest_event_id=latest_event_id)


if __name__ == "__main__":
    # Get the inputs from environment variables
    # main()
    pass