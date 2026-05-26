from typing import TypedDict
from langgraph.graph import StateGraph, END


class State(TypedDict):
    name: str
    greeting: str
    shout: str


def greeter(state: State):
    return {"greeting": f"Hello {state['name']}"}


def shouter(state: State):
    return {"shout": state["greeting"].upper()}


graph = StateGraph(State)

graph.add_node("greeter", greeter)
graph.add_node("shouter", shouter)

graph.set_entry_point("greeter")
graph.add_edge("greeter", "shouter")
graph.add_edge("shouter", END)

app = graph.compile()


if __name__ == "__main__":
    result = app.invoke({"name": "Alice"})
    print(result)
