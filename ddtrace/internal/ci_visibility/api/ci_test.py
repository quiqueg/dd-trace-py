from typing import Dict
from typing import List
from typing import Optional

from ddtrace.ext import test
from ddtrace.ext.ci_visibility.api import CIExcInfo
from ddtrace.ext.ci_visibility.api import CISourceFileInfo
from ddtrace.ext.ci_visibility.api import CITestId
from ddtrace.ext.ci_visibility.api import CITestStatus
from ddtrace.internal.ci_visibility.api.ci_base import CIVisibilityChildItem
from ddtrace.internal.ci_visibility.api.ci_base import CIVisibilityItemBase
from ddtrace.internal.ci_visibility.api.ci_base import CIVisibilitySessionSettings
from ddtrace.internal.ci_visibility.constants import TEST
from ddtrace.internal.logger import get_logger


log = get_logger(__name__)


class CIVisibilityTest(CIVisibilityChildItem[CITestId], CIVisibilityItemBase):
    event_type = TEST

    def __init__(
        self,
        item_id: CITestId,
        session_settings: CIVisibilitySessionSettings,
        codeowners: Optional[List[str]] = None,
        source_file_info: Optional[CISourceFileInfo] = None,
        initial_tags: Optional[Dict[str, str]] = None,
        is_early_flake_retry: bool = False,
    ):
        super().__init__(item_id, session_settings, initial_tags)
        self.parameters = item_id.parameters
        self._codeowners = codeowners
        self._source_file_info = source_file_info
        self._original_test: Optional[CIVisibilityTest] = None
        self._is_early_flake_retry = is_early_flake_retry  # NOTE: currently unused
        self._operation_name = session_settings.test_operation_name
        self._exc_info: Optional[CIExcInfo] = None

        if item_id.parameters:
            self.set_tag(test.PARAMETERS, item_id.parameters)

    def _get_hierarchy_tags(self) -> Dict[str, str]:
        return {
            test.NAME: self.name,
        }

    def _set_span_tags(self):
        """This handles setting tags that can't be properly stored in self._tags

        - exc_info: because it uses span.set_exc_info()
        """
        if self._exc_info is not None:
            self._span.set_exc_info(self._exc_info.exc_type, self._exc_info.exc_value, self._exc_info.exc_traceback)

    def start(self):
        log.debug("Starting CI Visibility test %s", self.item_id)
        super().start()

    def finish_test(
        self,
        status: CITestStatus,
        reason: Optional[str] = None,
        exc_info: Optional[CIExcInfo] = None,
        is_itr_skipped: bool = False,
    ):
        log.debug("Finishing CI Visibility test %s, with status: %s, reason: %s", self.item_id, status, reason)
        self.set_status(status)
        if reason is not None:
            self.set_tag(test.SKIP_REASON, reason)
        elif is_itr_skipped:
            self.mark_itr_skipped()
        if exc_info is not None:
            self._exc_info = exc_info
        super().finish()

    @classmethod
    def make_early_flake_retry_from_test(cls, original_test, retry_number: int):
        new_test_id = CITestId(
            original_test.item_id.parent_id, original_test.name, original_test.parameters, retry_number
        )
        return cls(
            new_test_id,
            original_test._session_settings,
            codeowners=original_test._codeowners,
            source_file_info=original_test._source_file_info,
            initial_tags=original_test._tags,
            is_early_flake_retry=True,
        )
