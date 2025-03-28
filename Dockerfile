# Use an official Python runtime as a parent image
FROM python:3.12-slim

# Set the working directory in the container
WORKDIR /app

# Copy the current directory contents into the container
COPY . /app

# Install any needed dependencies specified in requirements.txt
RUN pip install --no-cache-dir .

# Run main.py when the container launches
CMD ["python", "src/main.py"]