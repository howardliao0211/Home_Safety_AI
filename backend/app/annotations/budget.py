"""Run mask CPU work in a killable process within the operation deadline."""

import asyncio
import multiprocessing
import threading
import time

# Concurrent attempts share one instance; cap simultaneous decode processes
# (CPU and memory) while each attempt keeps its own deadline.
SLOTS = threading.BoundedSemaphore(4)
# multiprocessing reaps every child on start(); concurrent attempts would race on
# waitpid, so process start and teardown are serialised.
LIFECYCLE = threading.Lock()


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
    # Non-blocking polling cannot leak a slot when the attempt is cancelled.
    while not SLOTS.acquire(blocking=False):
        await asyncio.sleep(min(0.01, remaining(deadline)))
    try:
        return await _bounded_cpu(function, arguments, deadline)
    finally:
        SLOTS.release()


async def _bounded_cpu(function, arguments, deadline):
    context = multiprocessing.get_context("spawn")
    receiver, sender = context.Pipe(duplex=False)
    process = context.Process(target=_compute, args=(sender, function, arguments), daemon=True)
    with LIFECYCLE:
        process.start()
    sender.close()
    try:
        # A child that dies closes the pipe, so poll() also wakes on interruption.
        while not receiver.poll():
            await asyncio.sleep(min(0.01, remaining(deadline)))
        try:
            succeeded, value = receiver.recv()
        except EOFError:
            raise ValueError("Mask computation interrupted") from None
        remaining(deadline)
        if not succeeded:
            raise ValueError("Invalid mask computation")
        return value
    finally:
        receiver.close()
        with LIFECYCLE:
            if process.is_alive():
                process.terminate()
            process.join(timeout=0.1)
            if process.is_alive():
                process.kill()
                # SIGKILL cannot be ignored; reap it so close() never sees a live child.
                process.join()
            process.close()
