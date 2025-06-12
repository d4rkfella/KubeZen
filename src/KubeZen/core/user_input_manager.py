from __future__ import annotations
import shlex
import tempfile
import os
import json
import stat
from typing import TYPE_CHECKING, List, Dict, cast, Optional, Callable, Any
from dataclasses import dataclass, field

from .service_base import ServiceBase
from .exceptions import UserInputCancelledError, UserInputFailedError

if TYPE_CHECKING:
    from .app_services import AppServices


@dataclass
class InputSpec:
    """Defines a single piece of input to be requested from the user."""

    result_key: str
    prompt_message: str
    default_value: str = ""
    validator: Optional[Callable[[str], None]] = field(default=None, repr=False)
    validation_error_message: str = "Invalid input."


class UserInputManager(ServiceBase):
    def __init__(self, app_services: AppServices):
        super().__init__(app_services)

    async def initialize(self) -> None:
        """Initialize the UserInputManager service."""
        self.logger.debug("Initializing UserInputManager...")
        # Currently no initialization needed, but keeping the method for consistency
        # and potential future initialization requirements
        self.logger.info("UserInputManager initialized successfully.")

    async def get_multiple_inputs(
        self, specs: List[InputSpec], task_name: str = "Multi-Input"
    ) -> Dict[str, str]:
        if not self.app_services.tmux_ui_manager:
            raise UserInputFailedError("TmuxUIManager is not available.")

        while True:  # Validation loop
            script_file_path = ""
            try:
                # This block generates and runs a single script for all inputs
                with tempfile.NamedTemporaryFile(
                    mode="w", delete=True, suffix=".json"
                ) as result_file_obj:
                    result_file_path = result_file_obj.name

                with tempfile.NamedTemporaryFile(
                    mode="w", delete=False, suffix=".sh"
                ) as script_file_obj:
                    script_file_path = script_file_obj.name

                script_parts = [
                    "#!/bin/bash",
                    "set -e",
                    # On Ctrl+C, write an empty JSON to the result file to signify cancellation
                    f'trap \'echo "{{}}" > "{result_file_path}"; rm -f "{script_file_path}"; exit 130\' INT',
                    "exec < /dev/tty",
                    "RESULTS_JSON='{}'",
                ]
                for spec in specs:
                    prompt = spec.prompt_message.replace("'", "\\'")
                    quoted_default = shlex.quote(spec.default_value)
                    script_parts.extend(
                        [
                            f"read -r -e -p $'{prompt}' INPUT_VALUE",
                            f'if [ -z "$INPUT_VALUE" ]; then INPUT_VALUE={quoted_default}; fi',
                            f"RESULTS_JSON=$(echo \"$RESULTS_JSON\" | jq --arg key '{spec.result_key}' --arg val \"$INPUT_VALUE\" '. + {{($key): $val}}')",
                        ]
                    )

                script_parts.append(f'echo "$RESULTS_JSON" > "{result_file_path}"')
                input_script_content = "\n".join(script_parts)

                with open(script_file_path, "w") as f:
                    f.write(input_script_content)
                os.chmod(script_file_path, stat.S_IRWXU)

                result_json_str = await self.app_services.tmux_ui_manager.execute_command_in_input_pane(
                    command_str=script_file_path,
                    result_file_path=result_file_path,
                    task_name=task_name,
                )

                results = cast(dict[str, str], json.loads(result_json_str or "{}"))
                if not results:
                    raise UserInputCancelledError("User cancelled input.")

                # Post-retrieval validation
                for spec in specs:
                    if spec.validator:
                        value_to_validate = results.get(spec.result_key, "")
                        spec.validator(value_to_validate)

                return results  # Success

            except ValueError as e:
                # Find which spec failed for a better error message
                error_message = f"Invalid input: {e}"
                await self.app_services.tmux_ui_manager.show_toast(
                    message=error_message, bg_color="black", fg_color="yellow", duration=5
                )
                # Loop will continue, re-prompting for all values
            except (UserInputCancelledError, UserInputFailedError) as e:
                raise e  # Propagate cancellation
            finally:
                if script_file_path and os.path.exists(script_file_path):
                    os.remove(script_file_path)

    async def get_single_input(self, prompt_text: str, initial_value: str = "") -> str:
        spec = InputSpec(
            result_key="single_value",
            prompt_message=prompt_text,
            default_value=initial_value,
        )
        results = await self.get_multiple_inputs([spec], task_name="Single-Input")
        return results.get("single_value", "")
