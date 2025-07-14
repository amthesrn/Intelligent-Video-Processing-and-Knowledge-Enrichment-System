

import logging
import json


class HumanReadableFormatter(logging.Formatter):
    def format(self, record):
        formatted_message = f"{self.formatTime(record)} - {record.levelname} - "
        formatted_message += record.getMessage()
        return formatted_message


def setup_logger():
    logger = logging.getLogger("client_logger")
    logger.setLevel(logging.DEBUG)

    if logger.hasHandlers():
        logger.handlers.clear()

    fh = logging.FileHandler("client_logger.log", mode="w", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    formatter = HumanReadableFormatter('%(asctime)s - %(levelname)s - %(message)s')
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    return logger


def clean_result(result):
    if isinstance(result, dict):
        if 'content' in result:
            if isinstance(result['content'], list):
                return '\n'.join([clean_result(item) for item in result['content']])
            return str(result['content'])
        if 'text' in result:
            return str(result['text'])
        return '\n'.join([str(v) for v in result.values() if isinstance(v, str)])
    elif isinstance(result, list):
        return '\n'.join([clean_result(item) for item in result])
    elif isinstance(result, str):
        return result.strip()
    else:
        return str(result)


def log_event(logger, event, print_to_console=True):
    if not hasattr(log_event, "_last_tool_result"):
        log_event._last_tool_result = None

    # Step 1: Extract clean text from event.content
    try:
        if hasattr(event, "content"):
            parsed = json.loads(event.content)
        else:
            parsed = json.loads(str(event))
        clean = clean_result(parsed)
    except Exception:
        clean = clean_result(str(event))

    # Step 2: Categorize event for output
    if "UserInputRequestedEvent" in str(event):
        msg = "[System]: Waiting for user input..."
    elif "ToolCallRequestEvent" in str(event):
        msg = "[System]: Calling tool..."
    elif "ToolCallExecutionEvent" in str(event):
        if clean == log_event._last_tool_result:
            return  # ✅ Skip both print and log
        log_event._last_tool_result = clean
        msg = f"📡 {clean}"
    elif "ToolCallSummaryMessage" in str(event):
        if clean == log_event._last_tool_result:
            return  # ✅ Skip both print and log
        log_event._last_tool_result = clean
        msg = f"✅ {clean}"
    elif "TextMessage" in str(event):
        msg = clean
    elif "TaskResult" in str(event):
        msg = "[System]: Task completed."
    else:
        msg = clean

    # Step 3: Output to terminal and log file
    if print_to_console:
        print("\n" + msg)

    logger.info(msg)
