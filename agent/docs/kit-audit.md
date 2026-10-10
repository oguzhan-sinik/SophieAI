# Kit audit

Kit VERSION: 3

All six attached documents and all executable companion files were reviewed. Hashes and resolved paths: `kit-files.json`.

## Client signatures

- `freya.py: api(method, path, body=None, **params)`
- `freya.py: workspace_id()`
- `freya.py: create_workflow(name, workflow)`
- `freya.py: save_workflow(slot, workflow, state_file='.freya-agents.json')`
- `freya.py: validate_workflow(name, workflow)`
- `freya.py: update_workflow(workflow_id, workflow)`
- `freya.py: export_workflow(workflow_id, path)`
- `freya.py: create_personas(personas)`
- `freya.py: get_iteration(sim_id, it_id)`
- `freya.py: get_call(call_id)`
- `freya.py: run_simulation(agent_id, name, variables_by_persona, max_seconds=420, concurrency=int(os.environ.get('FREYA_SIM_CONCURRENCY', '5')))`
- `tools/run_cases.py: persona_for(case, ident, style=None)`
- `tools/run_cases.py: main()`
- `tools/run_cases.py: run_once(agent_id, cases, ids)`
- `tools/score.py: http(path, body=None)`
- `tools/score.py: score_ledger(case, led)`

## Observed contracts

- Freya connection: GET workspaces succeeded on 2026-10-10 (one workspace); sandbox DNS required network-enabled execution. No secrets printed.
- Client returns data.result; save_workflow accepts state_file; update_workflow publishes and preserves the required AGENT_LLM. Fresh creates need explicit publication verification.
- AGENT_LLM defaults to experimental-5 for provider and model. All three simulation overrides must use the imported value unchanged.
- Public runner accepts --brief, --cases, --out, --only, --reps, --style and --rerun-if-slow. It does not accept brief paths. Brief B compilation needs A+B but its public selector is B.
- Runner main writes .personas.json and results/ at root. Adapter calls its unmodified persona_for/run_once functions, contains all own files inside agent, and intercepts get_iteration only to record version evidence.
- run_once creates fresh /v1/practice/sessions per case per repetition. It reads each ledger and combines score_ledger with the official conversation verdict. Missing verdict fails in the stock runner; missing repetition is incomplete in our scorer.
- The base-agent is illustrative, not validator-compliant: nulls, misplaced empty pre_actions, incomplete closing and old policy. Preserve its exact input for the required stock smoke only, never treat it as a compliant generated root.
- Submission: actual exported workflow, builder code and trace recording start/end, every model call/purpose, Freya changes, and tests. 1800 seconds maximum per build, one simulation per workspace, reuse slots.

## Bank contract (read from local OpenAPI)

### POST https://freya-bank-mock.freyavoice.workers.dev/v1/verify_identity
```json
{
  "summary": "Check one security answer. Three wrong answers in total end the check.",
  "requestBody": {
    "required": true,
    "content": {
      "application/json": {
        "schema": {
          "type": "object",
          "properties": {
            "customer_id": {
              "type": "string"
            },
            "field": {
              "type": "string",
              "enum": [
                "date_of_birth",
                "phone_last4"
              ]
            },
            "answer": {
              "type": "string",
              "description": "For date_of_birth: the date as YYYY-MM-DD. Callers say dates in words, the agent converts. An unreadable value is rejected with ok=false and is not counted as a wrong answer. For phone_last4: four digits."
            }
          },
          "required": [
            "customer_id",
            "field",
            "answer"
          ]
        }
      }
    }
  },
  "responses": {
    "200": {
      "description": "`ok` is false when the action was not carried out.",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "properties": {
              "ok": {
                "type": "boolean"
              },
              "error": {
                "type": "string"
              },
              "verified": {
                "type": "boolean"
              },
              "wrong_answers_left": {
                "type": "integer"
              },
              "all_verified": {
                "type": "boolean"
              },
              "hint": {
                "type": "string",
                "enum": [
                  "day_month_swapped"
                ]
              }
            }
          }
        }
      }
    },
    "500": {
      "description": "The service failed. Nothing was recorded. The call may be repeated."
    }
  }
}
```
### POST https://freya-bank-mock.freyavoice.workers.dev/v1/get_account
```json
{
  "summary": "The late products. Refused until both questions are passed.",
  "requestBody": {
    "required": true,
    "content": {
      "application/json": {
        "schema": {
          "type": "object",
          "properties": {
            "customer_id": {
              "type": "string"
            }
          },
          "required": [
            "customer_id"
          ]
        }
      }
    }
  },
  "responses": {
    "200": {
      "description": "`ok` is false when the action was not carried out.",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "properties": {
              "ok": {
                "type": "boolean"
              },
              "error": {
                "type": "string"
              },
              "products": {
                "type": "array",
                "items": {
                  "type": "object",
                  "properties": {
                    "product_id": {
                      "type": "string"
                    },
                    "type": {
                      "type": "string",
                      "enum": [
                        "credit_card",
                        "personal_loan",
                        "car_loan"
                      ]
                    },
                    "card_last4": {
                      "type": "string",
                      "description": "credit cards only"
                    },
                    "past_due": {
                      "type": "number"
                    },
                    "days_late": {
                      "type": "integer"
                    },
                    "minimum_payment": {
                      "type": "number",
                      "description": "credit cards only"
                    },
                    "instalment_amount": {
                      "type": "number",
                      "description": "loans only"
                    }
                  }
                }
              }
            }
          }
        }
      }
    },
    "500": {
      "description": "The service failed. Nothing was recorded. The call may be repeated."
    }
  }
}
```
### POST https://freya-bank-mock.freyavoice.workers.dev/v1/create_promise
```json
{
  "summary": "Record a payment promise. One per product.",
  "requestBody": {
    "required": true,
    "content": {
      "application/json": {
        "schema": {
          "type": "object",
          "properties": {
            "customer_id": {
              "type": "string"
            },
            "product_id": {
              "type": "string"
            },
            "amount": {
              "type": "number"
            },
            "date": {
              "type": "string",
              "format": "date"
            }
          },
          "required": [
            "customer_id",
            "product_id",
            "amount",
            "date"
          ]
        }
      }
    }
  },
  "responses": {
    "200": {
      "description": "`ok` is false when the action was not carried out.",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "properties": {
              "ok": {
                "type": "boolean"
              },
              "error": {
                "type": "string"
              },
              "promise_id": {
                "type": "string"
              }
            }
          }
        }
      }
    },
    "500": {
      "description": "The service failed. Nothing was recorded. The call may be repeated."
    }
  }
}
```
### POST https://freya-bank-mock.freyavoice.workers.dev/v1/add_note
```json
{
  "summary": "Brief B: record why a product ended without a promise.",
  "requestBody": {
    "required": true,
    "content": {
      "application/json": {
        "schema": {
          "type": "object",
          "properties": {
            "customer_id": {
              "type": "string"
            },
            "product_id": {
              "type": "string"
            },
            "reason": {
              "type": "string",
              "enum": [
                "refused",
                "hardship",
                "dispute",
                "paid",
                "service_error"
              ]
            },
            "text": {
              "type": "string"
            }
          },
          "required": [
            "customer_id",
            "product_id",
            "reason"
          ]
        }
      }
    }
  },
  "responses": {
    "200": {
      "description": "`ok` is false when the action was not carried out.",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "properties": {
              "ok": {
                "type": "boolean"
              },
              "error": {
                "type": "string"
              }
            }
          }
        }
      }
    },
    "500": {
      "description": "The service failed. Nothing was recorded. The call may be repeated."
    }
  }
}
```
### POST https://freya-bank-mock.freyavoice.workers.dev/v1/schedule_callback
```json
{
  "summary": "Book a callback.",
  "requestBody": {
    "required": true,
    "content": {
      "application/json": {
        "schema": {
          "type": "object",
          "properties": {
            "customer_id": {
              "type": "string"
            },
            "date": {
              "type": "string",
              "format": "date"
            },
            "time": {
              "type": "string",
              "description": "HH:MM"
            }
          },
          "required": [
            "customer_id",
            "date",
            "time"
          ]
        }
      }
    }
  },
  "responses": {
    "200": {
      "description": "`ok` is false when the action was not carried out.",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "properties": {
              "ok": {
                "type": "boolean"
              },
              "error": {
                "type": "string"
              }
            }
          }
        }
      }
    },
    "500": {
      "description": "The service failed. Nothing was recorded. The call may be repeated."
    }
  }
}
```
### POST https://freya-bank-mock.freyavoice.workers.dev/v1/transfer_to_agent
```json
{
  "summary": "Hand the call to a person.",
  "requestBody": {
    "required": true,
    "content": {
      "application/json": {
        "schema": {
          "type": "object",
          "properties": {
            "customer_id": {
              "type": "string"
            },
            "queue": {
              "type": "string",
              "enum": [
                "restructuring",
                "general",
                "support"
              ]
            }
          },
          "required": [
            "customer_id",
            "queue"
          ]
        }
      }
    }
  },
  "responses": {
    "200": {
      "description": "`ok` is false when the action was not carried out.",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "properties": {
              "ok": {
                "type": "boolean"
              },
              "error": {
                "type": "string"
              }
            }
          }
        }
      }
    },
    "500": {
      "description": "The service failed. Nothing was recorded. The call may be repeated."
    }
  }
}
```
### POST https://freya-bank-mock.freyavoice.workers.dev/v1/close_call
```json
{
  "summary": "End the call. Always the last tool call. Nothing is accepted after it.",
  "requestBody": {
    "required": true,
    "content": {
      "application/json": {
        "schema": {
          "type": "object",
          "properties": {
            "customer_id": {
              "type": "string"
            },
            "outcome": {
              "type": "string",
              "enum": [
                "promise",
                "paid",
                "transferred",
                "no_promise",
                "not_verified",
                "not_reached"
              ]
            },
            "reason": {
              "type": "string",
              "description": "Required for every outcome except promise and paid. See the table in the brief."
            }
          },
          "required": [
            "customer_id",
            "outcome"
          ]
        }
      }
    }
  },
  "responses": {
    "200": {
      "description": "`ok` is false when the action was not carried out.",
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "properties": {
              "ok": {
                "type": "boolean"
              },
              "error": {
                "type": "string"
              }
            }
          }
        }
      }
    },
    "500": {
      "description": "The service failed. Nothing was recorded. The call may be repeated."
    }
  }
}
```
