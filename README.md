# Cognex EtherNet/IP Monitor

A Python desktop application for monitoring and controlling Cognex Class 1
EtherNet/IP I/O. It supports Input Assembly 13, Output Assembly 22, raw I/O
inspection, output controls, and configurable packed PLC data layouts.

## Requirements

- Python 3.10 or newer
- A Python installation with Tkinter support
- Network access to the Cognex device on TCP port 44818 and UDP port 2222

## Setup

Clone the repository and enter its directory:

```powershell
git clone https://github.com/foxrid3r/cognex_eip.git
cd cognex_eip
```

Create a virtual environment and install the application into it:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install .
```

This performs a normal installation. Users can run the application without
editing the source code, and changes to files in the repository will not alter
the installed application. No third-party runtime packages are currently
required.

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

Contributors who intend to change the source should install the application in
editable mode:

```powershell
.venv\Scripts\Activate.ps1
python -m pip install --editable .
```

Editable installation makes source changes available without reinstalling the
application.

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
