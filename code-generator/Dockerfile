# Use the official lightweight Python 3.13 image.
# The "slim" variant keeps the image smaller than the full Python image.
FROM python:3.13-slim

# Prevent Python from writing .pyc files inside the container.
ENV PYTHONDONTWRITEBYTECODE=1

# Make Python output unbuffered so logs appear immediately in the console.
ENV PYTHONUNBUFFERED=1

# Add the application source directory to PYTHONPATH
# so the "codegen" package can be imported correctly.
ENV PYTHONPATH=/app/src

# Set the working directory inside the container.
# All subsequent commands will run from this folder.
WORKDIR /app

# Copy the dependency file first.
# This helps Docker cache the dependency installation layer
# so it does not reinstall packages every time the source code changes.
COPY requirements.txt .

# Install Python dependencies.
RUN pip install --no-cache-dir -r requirements.txt

# Copy the application source code into the container.
COPY src ./src

# Define the default executable for the container.
# The application is launched as a package module so imports such as
# "from codegen.version import __version__" work correctly.
# Additional arguments passed to "docker run" will be appended automatically.
ENTRYPOINT ["python", "-m", "codegen.main"]