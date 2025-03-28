from pathlib import Path
import time
import docker

def synapse_container():
    """Start Synapse container for integration tests."""
    client = docker.from_env()

    # Create temporary directory for Synapse data
    data_dir = Path("./synapse-data")

    if not data_dir.exists():
        data_dir.mkdir(exist_ok=True)

        # Generate initial configuration using migrate_config
        client.containers.run(
            "matrixdotorg/synapse:latest",
            "migrate_config",
            remove=True,
            environment={
                "SYNAPSE_SERVER_NAME": "test.local",
                "SYNAPSE_REPORT_STATS": "no",
                "SYNAPSE_ENABLE_REGISTRATION": "yes",
                "SYNAPSE_NO_TLS": "yes",
                "SYNAPSE_LOG_LEVEL": "INFO",
            },
            volumes={str(data_dir.absolute()): {"bind": "/data", "mode": "rw"}},
        )
        line_to_write = "\nenable_registration_without_verification: true\n"

        # Add registration without verification to the generated config
        with open(data_dir / "homeserver.yaml", "a") as f:
            f.write(line_to_write)

        # Replace all instances of `/homeserver.log` with `/data/homeserver.log`
        # in log.config
        with open(data_dir / "log.config", "r") as f:
            log_config = f.read()
            log_config = log_config.replace("/homeserver.log", "/data/homeserver.log")
        with open(data_dir / "log.config", "w") as f:
            f.write(log_config)

    else:
        # Remove old logging files
        for file in data_dir.glob("*.log"):
            file.unlink()

    # Start Synapse with the generated config
    container = client.containers.run(
        "matrixdotorg/synapse:latest",
        detach=True,
        remove=True,
        environment={
            "SYNAPSE_LOG_LEVEL": "INFO",
            "SYNAPSE_ENABLE_REGISTRATION_WITHOUT_VERIFICATION": "true",
        },
        volumes={str(data_dir.absolute()): {"bind": "/data", "mode": "rw"}},
        ports={"8008/tcp": 8008},
    )

    def _cleanup():
        container.stop()
        # Clean up data directory
        for file in data_dir.glob("*"):
            if file.is_file():
                file.unlink()
            else:
                file.rmdir()
        data_dir.rmdir()

    # Wait for Synapse to be ready
    max_retries = 30
    retry_interval = 4
    for _ in range(max_retries):
        try:
            # # Check if string is in logging file
            # with open(data_dir / "homeserver.log") as f:
            #     logs = f.read()
            #     if "Synapse now listening on TCP port 8008" in logs:
            #         break
            logs = container.logs().decode("utf-8")
            if "Synapse now listening on TCP port 8008" in logs:
                break
        except Exception:
            pass
        except KeyboardInterrupt:
            _cleanup()
            raise KeyboardInterrupt
        time.sleep(retry_interval)
    else:
        raise TimeoutError("Synapse failed to start within the expected time")

    # Create admin user
    container.exec_run(
        [
            "register_new_matrix_user",
            "-c",
            "/data/homeserver.yaml",
            "--admin",
            "-u",
            "admin",
            "-p",
            "admin_password",
            "http://localhost:8008",
        ]
    )

    try:
        yield {
            "homeserver": "http://localhost:8008",
            "user": "@admin:test.local",
            "password": "admin_password",
            "room_id": "!test:test.local",
        }
    finally:
        _cleanup()