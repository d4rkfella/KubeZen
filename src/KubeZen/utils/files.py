import tempfile
import shlex


def create_temp_file_and_get_command(content: str, file_prefix: str) -> str:
    """Creates a temporary file and returns a command to view it.
    Creates a temporary file with the given content and returns a command
    to view it using the system's default pager (e.g., less).
    """
    with tempfile.NamedTemporaryFile(
        mode="w", delete=False, prefix=file_prefix, suffix=".yaml"
    ) as tmp_file:
        tmp_file.write(content)
        temp_file_path = tmp_file.name

        # Use 'less' with options for a better viewing experience.
        # -R: render ANSI color escapes
        # -F: exit if the entire file can be displayed on one screen
        # -X: don't clear the screen on exit
        return f"less -R -F -X {shlex.quote(temp_file_path)}"
