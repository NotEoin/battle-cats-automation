# Contributing

Thank you for helping. Reports from devices nobody has tested are the most
useful thing right now: see [Report a new device](docs/howto/report-a-new-device.md).

## Changing the code

1. Read the [developer guide](docs/developer-guide.md) for how the parts fit.
2. Set up and check the tests pass before you change anything:

   ```
   uv venv && uv pip install -e ".[test]"    # editable install with pytest and ruff
   uv run pytest                             # needs no device and no network
   ```

3. Make the change, with a test. A bug fix comes with a test that fails
   without it.
4. Run `uv run pytest` and `uv run ruff check .` again.
5. Write the commit message as [COMMIT-CONVENTION.md](COMMIT-CONVENTION.md)
   says, and open a pull request.

## Rules the code follows

- Every module opens with a docstring saying what it is for, and every public
  function has a one-line docstring.
- Comments say why, not what.
- A number that is not obvious gets a named constant and says where it came
  from. Screen positions say which device they were measured on.
- Text is ASCII. Write other characters as escapes (`"\u2713"`).
- Nothing is pressed that spends Cat Food or real money unless the person
  asked for it.
- No game screenshots go into git: the tests use synthetic fixtures.

## If something goes wrong

| Symptom | Fix |
|---|---|
| A test fails before you changed anything | Check you are on the newest `main`, then open an issue with the output. |
| `ruff` reports non-ASCII characters | Replace them, or write them as escapes in code. |
| A test needs an event the fixtures lack | Run `bcgacha tools update`, then `python scripts/make_test_data.py`. |
