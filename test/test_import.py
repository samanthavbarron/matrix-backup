import asyncio
import unittest
import docker
from time import sleep
import importlib
from nio import AsyncClient, RoomVisibility
from pathlib import Path

import sqlalchemy
from sqlalchemy.orm import Session
from synapse_server import synapse_container
from src.main import main
import sqlite3

class TestImport(unittest.IsolatedAsyncioTestCase):

    def test_import(self):
        importlib.import_module('src')
    
    def setUp(self):
        # Check to see if the synapse container is already running
        running = False
        for container in docker.DockerClient().containers.list():
            for tag in container.image.tags:
                if "synapse" in tag:
                    running = True
                    break

        if running:
            # Remove the container
            container.stop()
            sleep(5)

        # Remove old data
        if Path("./synapse-data").exists():
            for item in Path("./synapse-data").iterdir():
                if item.is_file():
                    if "homeserver.db" == item.name:
                        item.unlink()

        self.gen = synapse_container()
        self.container_info = next(self.gen)
        self.client = AsyncClient(
            homeserver=self.container_info['homeserver'],
            user=self.container_info['user'],
        )

    async def login(self):
        login_response = await self.client.login(self.container_info['password'])
        self.assertTrue(login_response.transport_response.ok)
        response = await self.client.sync()
        self.assertTrue(response.transport_response.ok)
    
    async def test_main(self):
        await self.login()

        _db_path = Path("./test_database.db")
        if _db_path.exists():
            _db_path.unlink()
        
        db_path = str(_db_path.absolute())
        db_url = f"sqlite+pysqlite:///{db_path}"
        engine = sqlalchemy.create_engine(db_url)
        with engine.connect() as conn:
            pass

        await self.client.register(username=f"test_user_a", password="password")
        await asyncio.sleep(2)

        users = [
            f"@test_user_a:test.local",
            self.container_info['user'],
        ]
        
        # Create some test rooms
        for i in range(2):
            room_response = await self.client.room_create(
                visibility=RoomVisibility.public,
                alias=f"test_{i}",
                name=f"Test Room {i}",
            )
            self.assertTrue(room_response.transport_response.ok)
            for user in users:
                invite_response = await self.client.room_invite(
                    room_id=room_response.room_id,
                    user_id=user,
                )
                if not invite_response.transport_response.ok:
                    if not "already in the room" in invite_response.message:
                        self.assertTrue(invite_response.transport_response.ok)

            # Send a test message
            message_response = await self.client.room_send(
                room_id=room_response.room_id,
                message_type="m.room.message",
                content={"body": f"Test message {i}", "msgtype": "m.text"},
            )
            self.assertTrue(message_response.transport_response.ok)
            await asyncio.sleep(1)
        
        await main(
            db_url=db_url,
            homeserver=self.container_info['homeserver'],
            user=self.container_info['user'],
            password=self.container_info['password'],
        )

        with Session(engine) as session:
            # Check the rooms table
            result = session.execute(sqlalchemy.text("SELECT * FROM rooms"))
            rooms = result.fetchall()
            self.assertEqual(len(rooms), 2)

            # Check the messages table
            result = session.execute(sqlalchemy.text("SELECT * FROM messages"))
            messages = result.fetchall()
            self.assertEqual(len(messages), 2)
            self.assertEqual(messages[0][4], "Test message 0")
            self.assertEqual(messages[1][4], "Test message 1")

        # Run again
        await main(
            db_url=db_url,
            homeserver=self.container_info['homeserver'],
            user=self.container_info['user'],
            password=self.container_info['password'],
        )
