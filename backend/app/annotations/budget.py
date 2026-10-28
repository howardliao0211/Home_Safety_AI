"""Run mask CPU work in a killable process within the operation deadline."""

import asyncio
import multiprocessing
import time


def remaining(deadline):
    seconds = deadline - time.monotonic()
    if seconds <= 0:
        raise TimeoutError()
    return seconds


def _compute(sender, function, arguments):
    try:
        sender.send((True, function(*arguments)))
    except Exception as exc:
        # Never transfer exception bodies containing raw provider/mask payloads.
        sender.send((False, type(exc).__name__))
    finally:
        sender.close()


async def bounded_cpu(function, *arguments, deadline):
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=_compute, args=(sender, function, arguments), daemon=True)
    process.start()
    sender.close()
    try:
        while not receiver.poll():
            remaining(deadline)
            if not process.is_alive():
                raise ValueError("Mask computation interrupted")
            await asyncio.sleep(min(0.01, remaining(deadline)))
        succeeded, value = receiver.recv()
        remaining(deadline)
        if not succeeded:
            raise ValueError("Invalid mask computation")
        return value
    finally:
        receiver.close()
        if process.is_alive():
            process.terminate()
        process.join(timeout=0.1)
        if process.is_alive():
            process.kill()
            process.join(timeout=0.1)
        process.close()
