"""Provider wire-name encoding, kept outside the agent's tool registry."""
import re
from ai.errors import ProviderResponseError


def tool_names(request):
    originals = {tool["function"]["name"] for tool in request.tools}
    originals.update(call.name for message in request.messages for call in message.tool_calls)
    mapping = {}
    for original in originals:
        encoded = original.replace(".", "__")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", encoded):
            raise ProviderResponseError("A tool name is not supported by this API.")
        if encoded in mapping and mapping[encoded] != original:
            raise ProviderResponseError("Tool names collide after provider encoding.")
        mapping[encoded] = original
    return mapping
