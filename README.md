# Cognex EtherNet/IP Monitor

A Python desktop application for monitoring and controlling Cognex Class 1
EtherNet/IP I/O. It supports Input Assembly 13, Output Assembly 22, raw I/O
inspection, output controls, and configurable packed PLC data layouts.

## Requirements

- Python 3.10 or newer
- A Python installation with Tkinter support
- Network access to the Cognex device on TCP port 44818 and UDP port 2222

## Setup

Clone the repository, enter its directory, and create a virtual environment:

```powershell
git clone <repository-url>
cd cognex_eip
python -m venv .venv
.venv\Scripts\Activate.ps1
```

Install the application in editable mode:

```powershell
python -m pip install --editable .
```

Editable installation keeps the command connected to the source checkout, so
code changes take effect without reinstalling the project. No third-party
runtime packages are currently required.

## Usage

After installation, start the application with:

```powershell
cognex-eip
```

It can also be launched as a Python module:

```powershell
python -m cognex_eip
```

Enter the camera IP address and requested packet interval, then select
**Connect**. Data layouts can be configured in the application and saved as
JSON files for reuse.

## Development

Run the standard-library test suite from the repository root:

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
```

The package is organized by responsibility:

```text
src/cognex_eip/
|-- binary.py       Binary assembly helpers
|-- connection.py   Threaded Class 1 connection service
|-- constants.py    Assembly definitions and defaults
|-- gui.py          Main Tk application
|-- layout.py       Configurable PLC data layouts
|-- protocol.py     EtherNet/IP and CIP packet handling
`-- widgets.py      Reusable Tk widgets
```

Hardware-independent behavior is covered by tests in `tests/`. Camera
communication requires integration testing against a Cognex device.

This repository is configured for local installation and collaboration. It
does not require publishing the project to PyPI.
