"""Cloud Doctor Layer 2 (client policy): OPA REST client with fail-closed handling."""
from .engine import Layer2Policy, decide
from .opa_client import (BundleStatus, Layer2Client, OpaHealthEndpoint, StaticBundleHealth, TransportError,
                         UrllibTransport)
from .opa_input import InputError, build_opa_input

__version__ = "l2-0.1"
__all__ = ["Layer2Client", "Layer2Policy", "decide", "BundleStatus", "StaticBundleHealth", "OpaHealthEndpoint",
           "UrllibTransport", "TransportError", "build_opa_input", "InputError"]
