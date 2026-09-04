# Contributing

Keep the plugin standalone: do not modify Hermes core to add printer-specific behavior. Add FDM printer support through data profiles and generic validation. Every behavior change needs a failing test, a focused implementation, and a passing `hermes plugins doctor . --ci` run.
