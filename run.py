import logging

import uvicorn

if __name__ == "__main__":
    # Without this, every log.info/log.warning in the services is silently
    # dropped -- including "ears: heard ..." and the boot sequence, which are
    # the two things you actually want to watch while using the HUD.
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%I:%M:%S %p",
    )
    logging.getLogger("jarvis").setLevel(logging.INFO)

    uvicorn.run("jarvis.app:app", host="127.0.0.1", port=8770, reload=False)
