from cerebro.jobs.app import app


def test_control_and_agent_tasks_are_isolated_by_queue() -> None:
    app.perform_import_paths()

    assert app.tasks["cerebro.jobs.tasks.process_slack_event"].queue == "control"
    assert app.tasks["cerebro.jobs.tasks.deliver_slack_output"].queue == "control"
    assert app.tasks["cerebro.jobs.tasks.recover_pending_work"].queue == "control"
    assert app.tasks["cerebro.jobs.tasks.operational_watchdog"].queue == "control"
    assert app.tasks["cerebro.jobs.tasks.execute_agent_run"].queue == "agent"
