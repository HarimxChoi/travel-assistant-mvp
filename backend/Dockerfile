# Dockerfile

# 1. Use an official Python base image.
# Using a specific version is good practice for reproducibility.
FROM python:3.10-slim

# 2. Set the working directory inside the container.
# All subsequent commands will run from this directory.
WORKDIR /app

# 3. Copy the file that lists our dependencies into the container.
COPY requirements.txt .

# 4. Install the dependencies.
# --no-cache-dir makes the image smaller.
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# 5. Copy the rest of our application's source code into the container.
# The '.' means copy everything from the current host directory (where Dockerfile is)
# to the current container directory ('/app').
COPY . .

# 6. Expose the port that our application will run on.
# This tells Docker that the container will listen on port 8008.
EXPOSE 8008

# 7. Define the command to run when the container starts.
# This is the command that starts our FastAPI server.
# We use 0.0.0.0 to listen on all available network interfaces, which is required for hosting.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8008"]