"""Run the Cognex EtherNet/IP GUI with python -m cognex_eip."""

from .gui import CognexGUI


def main():
    app = CognexGUI()
    app.mainloop()


if __name__ == "__main__":
    main()
