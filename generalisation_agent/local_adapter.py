"""Offline compiled artifacts only: no Freya client, credentials, network or simulation slot."""
from contextlib import contextmanager
from copy import deepcopy

from agent.builder.artifacts import digest, write_json
from agent.builder.freya_adapter import contains_definition


class LocalAdapter:
    local = True

    def __init__(self, cfg, deadline, trace):
        self.deadline, self.trace = deadline, trace
        self.deployment, self.exporting = None, False
        self.workflow = None

    @contextmanager
    def workspace(self):
        yield self

    def validate_remote(self, workflow):
        self.trace.event("local_compiled_only", platform_validation=False)

    def deploy(self, slot, workflow):
        self.deadline.require(export=self.exporting)
        self.workflow = deepcopy(workflow)
        self.deployment = {"workflow_hash": digest(workflow), "backend": "local_compiled", "slot": slot}
        self.trace.event("local_candidate", **self.deployment)

    def export(self, workflow, path):
        contains_definition(workflow, self.workflow)
        write_json(path, {"workflow": self.workflow, "backend": "local_compiled", "platform_export": False})
        return str(path)

    def evaluate(self, *args):
        raise ValueError("Offline rehearsal cannot run official public simulations")
