#!/usr/bin/env python
# -*- coding: UTF-8 -*-
#
# Copyright 2021-2023 NXP
#
# SPDX-License-Identifier: BSD-3-Clause

"""This Python script runs the development checks on SPSDK project."""

import concurrent.futures
import time
from concurrent.futures import CancelledError, Future
from concurrent.futures.process import ProcessPoolExecutor
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional

import colorama

from spsdk.exceptions import SPSDKError
from spsdk.utils.easy_enum import Enum

colorama.just_fix_windows_console()


class TaskState(Enum):
    """States of tasks."""

    READY = (0, "Ready")
    BLOCKED = (1, "Blocked")
    RUNNING = (2, "Running")
    PASSED = (3, "Passed")
    FAILED = (4, "Failed")


@dataclass
class TaskResult:
    error_count: int
    output_log: str


class TaskInfo:

    """Task information class."""

    def __init__(
        self,
        name: str,
        method: Callable,
        *args: Any,
        dependencies: Optional[List[str]] = None,
        inherit_failure: bool = True,
        info_only: bool = False,
        **kwargs: Any,
    ) -> None:
        """Task info initialization.
        :param name: Name of the task
        :param method: Method to be called in the task
        :param args: Argument to be passed into method
        :param kwargs: Keyword argument to be passed into method
        :param dependencies: Task names the actual task is dependent on
        :param inherit_failure: Fail the task immediately if the dependency fails
        :param info_only: This is just information task - fault of this task doesn't cause fail result
        """
        self.name = name
        self.method = method
        self.args = args
        self.kwargs = kwargs
        self.dependencies = dependencies
        self.inherit_failure = inherit_failure
        self.info_only = info_only
        self._state = TaskState.READY
        self.result: Optional[TaskResult] = None
        self.exec_start = 0.0
        self.exec_time = 0.0
        self.exception: Optional[BaseException] = None

    def __str__(self) -> str:
        """Print Task information."""
        return f"Task information:\nName: {self.name}\nMethod: {self.method}\nDependencies: {self.dependencies}"

    def __repr__(self) -> str:
        return f"<TaskInfo: {self.name} [{self.status_str()}] Depends: {self.dependencies}>"

    @property
    def status(self) -> TaskState:
        """Get task status.

        :return: Task status.
        """
        return self._state

    @status.setter
    def status(self, state: TaskState) -> None:
        """Setter of task status.

        :param state: New task status.
        """
        assert state in TaskState
        self._state = state

    def status_str(self) -> str:
        """Get task status in txt form.

        :return: Task state.
        """
        ret = f"{self.get_color_by_status()}{TaskState.name(self._state)}"
        if self.info_only:
            ret += f"{colorama.Fore.CYAN} [INFO ONLY]"
        ret += colorama.Fore.RESET
        return ret

    def start_task(self) -> None:
        """Start task event."""
        if self.is_failed():
            raise SPSDKError("The task is already failed.")

        self.exec_start = time.perf_counter()
        self.status = TaskState.RUNNING

    def finish_task(self, result: Optional[TaskResult], exc: Optional[BaseException]) -> None:
        """Finish task event."""
        if not self.is_running():
            raise SPSDKError("The task is not running.")

        exec_stop = time.perf_counter()
        self.exec_time = exec_stop - self.exec_start
        passed = not exc and result.error_count == 0 if result else not exc
        self.status = TaskState.PASSED if passed else TaskState.FAILED
        self.result = result
        self.exception = exc

    def is_finished(self) -> bool:
        """Get the state if the task is finished.

        :return: True if task is finished, otherwise False.
        """
        return self.status in [TaskState.PASSED, TaskState.FAILED]

    def is_failed(self) -> bool:
        """Get the state if the task is failed.

        :return: True if task is failed, otherwise False.
        """
        return self.status == TaskState.FAILED

    def is_ready(self) -> bool:
        """Get the state if the task is ready to be run.

        :return: True if task is finished, otherwise False.
        """
        return self.status == TaskState.READY

    def is_running(self) -> bool:
        """Get running state.

        :return: True if task is running, otherwise False.
        """
        return self.status == TaskState.RUNNING

    def get_color_by_status(self) -> colorama.Fore:
        """Get color of string by status of task.

        :return: Color from colorama schema
        """
        colors = {
            TaskState.READY: colorama.Fore.WHITE,
            TaskState.BLOCKED: colorama.Fore.MAGENTA,
            TaskState.RUNNING: colorama.Fore.YELLOW,
            TaskState.PASSED: colorama.Fore.GREEN,
            TaskState.FAILED: colorama.Fore.RED,
        }
        return colors[self.status]

    def get_exec_time(self) -> str:
        """Get execution time in string format.

        :return: Execution time information.
        """
        return str(round(self.exec_time, 1)) + "s"

    def reset(self) -> None:
        """Reset the task to its initial state."""
        self._state = TaskState.READY
        self.result = None
        self.exec_start = 0.0
        self.exec_time = 0.0


# pylint: disable=not-an-iterable,no-member
class TaskList(List[TaskInfo]):
    """Custom list for Task infos."""

    def append(self, __object: TaskInfo) -> None:
        super().append(__object)
        self._set_task_states()

    def extend(self, __iterable: Iterable[TaskInfo]) -> None:
        super().extend(__iterable)
        self._set_task_states()

    def _set_task_states(self) -> None:
        """Set the states to task by its dependencies."""
        for task in self:
            if task.status in [TaskState.READY, TaskState.BLOCKED]:
                depend_state = self.check_dependencies(task.dependencies)
                if depend_state != TaskState.FAILED:
                    task.status = depend_state
                else:
                    task.status = TaskState.FAILED if task.inherit_failure else TaskState.READY
                    if task.status == TaskState.FAILED:
                        task.exception = Exception("Failed due to dependency task is failed.")

    def all_finished(self) -> bool:
        """Get information if all tasks are finished.

        :return: True if any task is pending, otherwise False
        """
        return all(task.is_finished() for task in self)

    def get_task_by_name(self, name: str) -> TaskInfo:
        """Get the task from this list by its name.

        :param name: Task name.
        :raises SPSDKError: Task name is not in active task list.
        :return: Task info object.
        """
        for task in self:
            if task.name == name:
                return task
        raise SPSDKError(f"Task {name} not found in list.")

    def check_dependencies(self, dependencies: Optional[List[str]]) -> TaskState:
        """Checks dependencies if is blocking or not.

        :param dependencies: List of names of tasks that must be finished before this task.
        :raises SPSDKError: Dependency doesn't exits in task list.
        :return: 'Blocks', 'Failed', 'OK'
        """
        if not dependencies:
            return TaskState.READY

        for depend in dependencies:
            try:
                task = self.get_task_by_name(depend)
            except ValueError as exc:
                raise SPSDKError(f"Dependency '{depend}' doesn't exits in task list.") from exc
            task_dep_st = self.check_dependencies(task.dependencies)
            if task_dep_st in [TaskState.BLOCKED, TaskState.FAILED]:
                return task_dep_st

            if task.status == TaskState.FAILED:
                return TaskState.FAILED

            if task.status in [TaskState.READY, TaskState.RUNNING]:
                return TaskState.BLOCKED

        return TaskState.READY

    def get_ready_task(self) -> Optional[TaskInfo]:
        """Return task ready to be executed.

        :return: Task that could be executed.
        """
        self._set_task_states()
        for task in self:
            if task.status == TaskState.READY:
                return task

        return None

    def get_running_tasks(self) -> int:
        """GEt count of currently running tasks.

        :return: Count of running tasks.
        """
        return sum(task.is_running() for task in self)


class PrettyProcessRunner:
    """Parallel process running with nice processing table prints on console"""

    def __init__(
        self,
        tasks: TaskList,
        print_func: Optional[Callable] = None,
    ) -> None:
        """Initialize the Pretty parallel runner.

        :param tasks: Dictionary with task names and its methods to run.
        :param result_formatter: Result formatter function.
        """
        self.tasks = tasks
        self.process_time = 0.0
        self.print_func = print_func or print

    def run(self, concurrent_runs: int = 5, clear_console: bool = False) -> None:
        """Run all tasks in parallel and print status table.

        :param concurrent_runs: Maximal concurrent task runs at ones, defaults to 5
        :param clear_console: Clear automatically console lines with task statuses.
        """
        futures: Dict[Future, TaskInfo] = {}
        start_time = time.perf_counter()
        self._print_status(repaint=False)
        with concurrent.futures.ProcessPoolExecutor() as executor:
            while (
                not self.tasks.all_finished() and self.tasks.get_running_tasks() < concurrent_runs
            ):
                ready_task = self.tasks.get_ready_task()
                if not ready_task:
                    break
                self._schedule_user_task(executor, futures, ready_task)
                self._print_status()

            while not self.tasks.all_finished():
                concurrent.futures.wait(futures, return_when=concurrent.futures.FIRST_COMPLETED)
                while (
                    not self.tasks.all_finished()
                    and self.tasks.get_running_tasks() < concurrent_runs
                ):
                    ready_task = self.tasks.get_ready_task()
                    if not ready_task:
                        break
                    self._schedule_user_task(executor, futures, ready_task)
                self._print_status()

        self.process_time = time.perf_counter() - start_time
        if clear_console:
            self._clear_lines()

    def _clear_lines(self, lines_to_clear: Optional[int] = None) -> None:
        lines_cnt = lines_to_clear or len(self.tasks) + 1
        self.print_func("\033[A" * lines_cnt)

    def _print_status(self, repaint: bool = True) -> None:
        if repaint:
            self._clear_lines()
        for task in self.tasks:
            self.print_func(f"\033[K{task.name} -> {task.status_str()}")

    def _user_task_done_callback(  # pylint: disable=no-self-use
        self, future: Future, future_set: dict, task: TaskInfo
    ) -> None:
        try:
            exc = future.exception()
            result = None if exc else future.result()
        except (CancelledError, TimeoutError) as loc_exc:
            exc = loc_exc
            result = None
        future_set.pop(future)
        task.finish_task(result, exc)

    def _schedule_user_task(
        self, executor: ProcessPoolExecutor, future_set: dict, task: TaskInfo
    ) -> Future:
        task.start_task()
        future = executor.submit(task.method, *task.args, **task.kwargs)
        future.add_done_callback(lambda x: (self._user_task_done_callback(x, future_set, task)))
        future_set[future] = task
        return future
