# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 The MCP-Injector Authors (see AUTHORS).
"""MCP-Injector fault-injection middleware.

Implements the protocol-aware fault operators (OP0 through OP6) and the
persistence model (PERMANENT, TRANSIENT, INTERMITTENT) described in the
NeurIPS 2026 submission. Attached to a FastMCP proxy server via
``proxy_server.add_middleware(Injector(...))``.
"""

import asyncio
import json
import logging
import random
import string
import sys
import time
from typing import Optional, Sequence, Union

from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import Middleware, MiddlewareContext

from utils.artifacts import ArtifactsLayout, ensure_run_id, proxy_mode

logger = logging.getLogger(__name__)


class LoggingMiddleware(Middleware):
    """Middleware that logs all MCP operations."""

    async def on_message(self, context: MiddlewareContext, call_next):
        """Called for all MCP messages."""
        logger.info(f"MIDDLEWARE: Processing {context.method} from {context.source}")

        result = await call_next(context)

        logger.info(f"MIDDLEWARE: Completed {context.method}")
        return result


class Injector(Middleware):

    def __init__(
        self,
        fault_mode: Union[str, Sequence[str], None] = None,
        stack: str = 'mcpbench',
        seed: Optional[int] = None,
        task_id: str = 'unknown',
        model_name: str = 'unknown',
    ):
        super().__init__()
        if fault_mode is None:
            raise ValueError(
                "Injector requires a fault_mode. "
                "Pass a path string or a non-empty sequence of strings containing the path to the fault-mode JSON file."
            )
        # Normalise: accept a bare path string as well as a Sequence[str]
        self.fault_mode: Sequence[str] = [fault_mode] if isinstance(fault_mode, str) else fault_mode
        self.indices, self.probs, self.model = self.load_fm()
        self.activated_permanent = False
        self.activated_intermittent = False
        self.activated_transient = False
        self.injector = None

        run_id = ensure_run_id()
        layout = ArtifactsLayout(
            run_id=run_id,
            stack=stack,
            model=model_name,
            proxy_mode=proxy_mode(False, self.fault_mode),
            seed=seed,
        )
        self.logs_file = layout.proxy_log_path(task_id)

    def load_fm(self):
        fault_modes_file = f"{self.fault_mode[0]}"

        with open(fault_modes_file, "r") as f:
            data = json.load(f)

        entries = data["fault_mode"]
        indices = list(range(len(entries)))
        probs = [inj["probability"] for inj in entries]

        return indices, probs, entries

    def select_injector(self):
        if self.activated_permanent and not self.activated_transient and not self.activated_intermittent:
            return self.injector
        elif self.activated_intermittent and not self.activated_permanent and not self.activated_transient:
            if random.random() <= self.injector["persistence"]["deactivation_p"]:
                self.activated_intermittent = False
            return self.injector
        else:
            idx = random.choices(self.indices, weights=self.probs, k=1)[0]
            self.injector = self.model[idx]
            if self.injector["persistence"]["type"] == "PERMANENT":
                self.activated_permanent = True
            elif self.injector["persistence"]["type"] == "INTERMITTENT":
                self.activated_intermittent = True
            elif self.injector["persistence"]["type"] == "TRANSIENT":
                self.activated_transient = True
            return self.injector

    async def nullInjector(self, context: MiddlewareContext, call_next, parameters):

        logger.debug("Execution of null injector")

        return await call_next(context)

    async def randomWrongType(self, context: MiddlewareContext, call_next, parameters):

        logger.debug("Execution of random wrong type injector")

        result = await call_next(context)
        content = result.content[0].text

        if isinstance(content, bool):
            content = int(content)
        elif isinstance(content, int):
            content = float(content)
        elif isinstance(content, float):
            content = int(content)
        elif isinstance(content, str):
            content = {"text": content}
        elif isinstance(content, dict):
            content = json.dumps(content)

        result.content[0].text = content
        return result

    async def delay(self, context: MiddlewareContext, call_next, parameters):

        logger.debug("Execution of delay injector")

        delay = parameters["duration"]

        # Wait a few minutes before returning response
        await asyncio.sleep(delay)

        result = await call_next(context)

        return result

    async def dropCall(self, context: MiddlewareContext, call_next, parameters):

        logger.debug("Execution of drop call injector")

        result = await call_next(context)

        await asyncio.sleep(sys.maxsize)

        return result

    async def smallDelta(self, context: MiddlewareContext, call_next, parameters):

        logger.debug("Execution of small delta injector")

        result = await call_next(context)

        content = result.content[0].text
        words = content.split()
        delta_words = []

        for word in words:
            if random.random() <= parameters["probability_per_word"]:
                index = random.randint(0, len(word) - 1)
                delta_word = word[:index] + random.choice(string.ascii_letters) + word[index + 1:]
                delta_words.append(delta_word)
            else:
                delta_words.append(word)

        result.content[0].text = " ".join(delta_words)
        logger.debug("Small delta injector result content: %s", result.content)
        return result

    async def randomValue(self, context: MiddlewareContext, call_next, parameters):

        logger.debug("Execution of random value injector")

        result = await call_next(context)

        content = result.content[0].text
        words = content.split()
        delta_words = []

        for word in words:
            if random.random() <= parameters["probability_per_word"]:
                if not isinstance(word, str):
                    delta_word = random.randint(0, sys.maxsize)
                else:
                    delta_word = "".join(random.choice(string.ascii_letters) for _ in range(len(word)))
                delta_words.append(delta_word)
            else:
                delta_words.append(word)

        result.content[0].text = " ".join(delta_words)
        logger.debug("Random value injector result content: %s", result.content)
        return result

    async def errorMessage(self, context: MiddlewareContext, call_next, parameters):

        logger.debug("Execution of error message injector")

        tool_name = context.message.name

        # Raises ToolError
        raise ToolError(f"Access Denied to: {tool_name}")

    async def on_call_tool(self, context: MiddlewareContext, call_next):
        injector = self.select_injector()
        injector_name = injector["type"].split("_")[1]
        logger.debug("Selected injector: %s with persistence type: %s", injector_name, injector["persistence"]["type"])

        tool_name = context.message.name

        if tool_name in injector["targets"] or injector["targets"][0] == "global":
            status = None
            response = None
            error = None
            if self.activated_permanent or random.random() <= injector["persistence"]["activation_p"]:
                parameters = injector["parameters"]
                start_time = time.perf_counter()
                try:
                    response = await getattr(self, injector_name)(context, call_next, parameters)
                    status = "success"
                    if self.activated_transient:
                        self.activated_transient = False
                    return response
                except Exception as e:
                    error = str(e)
                    status = "failure"
                    raise ToolError(error)
                finally:
                    end_time = time.perf_counter()
                    elapsed_time = end_time - start_time
                    result = {
                        "status": status,
                        "tool": context.message.name,
                        "parameters": context.message.arguments,
                        "response_from_tool": response.content[0].text if response is not None else None,
                        "error": error,
                        "run_time": elapsed_time,
                        "type": injector["type"],
                        "persistence": injector["persistence"]["type"]
                    }

                    with open(self.logs_file, "a", encoding="utf-8") as f:
                        json.dump(result, f, ensure_ascii=False)
                        f.write("\n")

                    logger.debug("Fault injector log saved to %s", self.logs_file)
            else:
                return await call_next(context)

        else:
            return await call_next(context)
