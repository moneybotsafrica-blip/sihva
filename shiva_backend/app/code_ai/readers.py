from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any
from datetime import datetime
import structlog

logger = structlog.get_logger(__name__)


class LogReaderInterface(ABC):
    """Abstract interface for reading server logs."""

    @abstractmethod
    async def get_logs(
        self,
        service: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 1000,
    ) -> List[str]:
        """Retrieve logs for a specific service within a time range."""
        pass

    @abstractmethod
    async def search_logs(
        self,
        query: str,
        service: Optional[str] = None,
        limit: int = 100,
    ) -> List[str]:
        """Search logs for specific error patterns or messages."""
        pass


class CodeReaderInterface(ABC):
    """Abstract interface for reading source code."""

    @abstractmethod
    async def get_file_content(self, file_path: str) -> Optional[str]:
        """Retrieve the content of a specific file."""
        pass

    @abstractmethod
    async def get_directory_structure(self, path: str) -> List[str]:
        """Get the directory structure (list of files)."""
        pass

    @abstractmethod
    async def search_code(
        self,
        pattern: str,
        file_pattern: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Search code for specific patterns."""
        pass


class MockLogReader(LogReaderInterface):
    """Mock implementation of LogReader for testing."""

    def __init__(self):
        self.logs: Dict[str, List[str]] = {}

    def add_mock_logs(self, service: str, log_entries: List[str]):
        """Add mock log entries for testing."""
        if service not in self.logs:
            self.logs[service] = []
        self.logs[service].extend(log_entries)

    async def get_logs(
        self,
        service: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 1000,
    ) -> List[str]:
        """Return mock logs for the service."""
        return self.logs.get(service, [])[:limit]

    async def search_logs(
        self,
        query: str,
        service: Optional[str] = None,
        limit: int = 100,
    ) -> List[str]:
        """Search mock logs for the query."""
        all_logs = []
        if service:
            all_logs = self.logs.get(service, [])
        else:
            for service_logs in self.logs.values():
                all_logs.extend(service_logs)

        matching_logs = [log for log in all_logs if query.lower() in log.lower()]
        return matching_logs[:limit]


class MockCodeReader(CodeReaderInterface):
    """Mock implementation of CodeReader for testing."""

    def __init__(self):
        self.files: Dict[str, str] = {}

    def add_mock_file(self, file_path: str, content: str):
        """Add a mock file for testing."""
        self.files[file_path] = content

    async def get_file_content(self, file_path: str) -> Optional[str]:
        """Return mock file content."""
        return self.files.get(file_path)

    async def get_directory_structure(self, path: str) -> List[str]:
        """Return mock directory structure."""
        return [f for f in self.files.keys() if f.startswith(path)]

    async def search_code(
        self,
        pattern: str,
        file_pattern: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Search mock code for the pattern."""
        results = []
        for file_path, content in self.files.items():
            if file_pattern and not file_path.endswith(file_pattern):
                continue

            if pattern.lower() in content.lower():
                results.append({
                    "file_path": file_path,
                    "matching_lines": [
                        i + 1
                        for i, line in enumerate(content.split("\n"))
                        if pattern.lower() in line.lower()
                    ],
                })

        return results


class FileLogReader(LogReaderInterface):
    """Real implementation that reads from log files."""

    def __init__(self, log_directory: str = "/var/log"):
        self.log_directory = log_directory

    async def get_logs(
        self,
        service: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 1000,
    ) -> List[str]:
        """Read logs from file system."""
        # This would implement actual file reading
        # For now, return empty list as placeholder
        logger.warning(
            "FileLogReader not fully implemented - using placeholder",
            service=service,
        )
        return []

    async def search_logs(
        self,
        query: str,
        service: Optional[str] = None,
        limit: int = 100,
    ) -> List[str]:
        """Search logs in file system."""
        logger.warning(
            "FileLogReader search not fully implemented - using placeholder",
            query=query,
            service=service,
        )
        return []


class GitCodeReader(CodeReaderInterface):
    """Real implementation that reads from a Git repository."""

    def __init__(self, repo_path: str = "."):
        self.repo_path = repo_path

    async def get_file_content(self, file_path: str) -> Optional[str]:
        """Read file content from Git repository."""
        # This would implement actual Git file reading
        # For now, return None as placeholder
        logger.warning(
            "GitCodeReader not fully implemented - using placeholder",
            file_path=file_path,
        )
        return None

    async def get_directory_structure(self, path: str) -> List[str]:
        """Get directory structure from Git repository."""
        logger.warning(
            "GitCodeReader directory structure not fully implemented - using placeholder",
            path=path,
        )
        return []

    async def search_code(
        self,
        pattern: str,
        file_pattern: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Search code in Git repository."""
        logger.warning(
            "GitCodeReader search not fully implemented - using placeholder",
            pattern=pattern,
            file_pattern=file_pattern,
        )
        return []
