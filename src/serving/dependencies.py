from fastapi import Request


def get_model(request: Request):
    return request.app.state.model


def get_model_card(request: Request):
    return request.app.state.model_card


def get_order_store(request: Request):
    return request.app.state.order_store


def get_order_queue(request: Request):
    return request.app.state.order_queue


def get_worker(request: Request):
    return request.app.state.worker
