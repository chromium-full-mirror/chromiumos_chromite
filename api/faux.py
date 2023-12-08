# Copyright 2019 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Decorators to help handle mock calls and errors in the Build API."""

import functools
from typing import Any, Callable, Dict, Iterable, TYPE_CHECKING

from chromite.api import controller


if TYPE_CHECKING:
    from chromite.third_party.google.protobuf import message as protobuf_message

    from chromite.api import api_config


BuildAPIFunction = Callable[
    [
        "protobuf_message.Message",
        "protobuf_message.Message",
        "api_config.ApiConfig",
        Iterable[Any],
        Dict[Any, Any],
    ],
    int,
]


def all_responses(
    faux_result_factory: BuildAPIFunction,
) -> Callable[[BuildAPIFunction], BuildAPIFunction,]:
    """A decorator to handle all mock responses.

    This is syntactic sugar for handling all the mock response types in a
    single function.

    Args:
        faux_result_factory: A function with the same signature as a regular
            API endpoint function that populates the output with success or
            error results, as requested, without executing the endpoint.
    """
    # Get the decorators for each of the mock types, so we can compose them.
    success_fn = success(faux_result_factory)
    err_fn = error(faux_result_factory)

    def _decorator(func: BuildAPIFunction) -> BuildAPIFunction:
        f = success_fn(func)
        return err_fn(f)

    return _decorator


def all_empty(func: BuildAPIFunction) -> BuildAPIFunction:
    """Decorator to handle all mock responses with an empty output."""
    return empty_error(empty_success(func))


def success(
    faux_result_factory: BuildAPIFunction,
) -> Callable[[BuildAPIFunction], BuildAPIFunction,]:
    """A decorator to handle mock call responses.

    Args:
        faux_result_factory: A function with the same signature as a regular
            API endpoint function that populates the output
    """

    def decorator(func: BuildAPIFunction) -> BuildAPIFunction:
        @functools.wraps(func)
        def _success(
            request: "protobuf_message.Message",
            response: "protobuf_message.Message",
            config: "api_config.ApiConfig",
            *args: Any,
            **kwargs: Any,
        ) -> int:
            if config.mock_call:
                faux_result_factory(request, response, config, *args, **kwargs)
                return controller.RETURN_CODE_SUCCESS

            return func(request, response, config, *args, **kwargs)

        return _success

    return decorator


def empty_success(func: BuildAPIFunction) -> BuildAPIFunction:
    """A decorator to handle mock success responses with empty outputs."""

    @functools.wraps(func)
    def _empty_success(
        request: "protobuf_message.Message",
        response: "protobuf_message.Message",
        config: "api_config.ApiConfig",
        *args: Any,
        **kwargs: Any,
    ) -> int:
        if config.mock_call:
            return controller.RETURN_CODE_SUCCESS

        return func(request, response, config, *args, **kwargs)

    return _empty_success


def error(
    faux_error_factory: BuildAPIFunction,
) -> Callable[[BuildAPIFunction], BuildAPIFunction,]:
    """A decorator to handle mock error responses."""

    def decorator(func: BuildAPIFunction) -> BuildAPIFunction:
        @functools.wraps(func)
        def _error(
            request: "protobuf_message.Message",
            response: "protobuf_message.Message",
            config: "api_config.ApiConfig",
            *args: Any,
            **kwargs: Any,
        ) -> int:
            if config.mock_error:
                faux_error_factory(request, response, config, *args, **kwargs)
                return controller.RETURN_CODE_UNSUCCESSFUL_RESPONSE_AVAILABLE

            return func(request, response, config, *args, **kwargs)

        return _error

    return decorator


def empty_error(func: BuildAPIFunction) -> BuildAPIFunction:
    """A decorator to handle mock error responses with empty outputs."""

    @functools.wraps(func)
    def _empty_error(
        request: "protobuf_message.Message",
        response: "protobuf_message.Message",
        config: "api_config.ApiConfig",
        *args: Any,
        **kwargs: Any,
    ) -> int:
        if config.mock_error:
            return controller.RETURN_CODE_UNRECOVERABLE

        return func(request, response, config, *args, **kwargs)

    return _empty_error


def empty_completed_unsuccessfully_error(
    func: BuildAPIFunction,
) -> BuildAPIFunction:
    """A decorator to handle mock unsuccessful response with empty outputs."""

    @functools.wraps(func)
    def _empty_error(
        request: "protobuf_message.Message",
        response: "protobuf_message.Message",
        config: "api_config.ApiConfig",
        *args: Any,
        **kwargs: Any,
    ) -> int:
        if config.mock_error:
            return controller.RETURN_CODE_COMPLETED_UNSUCCESSFULLY

        return func(request, response, config, *args, **kwargs)

    return _empty_error
