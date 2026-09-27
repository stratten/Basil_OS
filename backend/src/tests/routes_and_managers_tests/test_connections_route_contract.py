from api.routes.connections import router


def test_slack_oauth_routes_are_registered() -> None:
    route_methods = {
        route.path: route.methods
        for route in router.routes
        if getattr(route, "methods", None)
    }

    assert route_methods["/settings/connections/slack/start_oauth"] == {"POST"}
    assert route_methods["/settings/connections/slack/complete_oauth"] == {"POST"}
