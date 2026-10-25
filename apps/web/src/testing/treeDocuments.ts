// Generated: the strict loader's parse of each scenario of
// packages/core/tests/data/scenarios/blocks/tree, as GET /api/v1/scenarios/{project}/{name}
// gives it as `document`. packages/generator/tests/unit/test_workflow_yaml.py checks it and
// rewrites it with GOLDEN_UPDATE=1. Tests read it through aTreeDocument (builders.ts).
export const TREE_DOCUMENTS: Readonly<Record<string, unknown>> = {
  "blocks-if-else": {
    "version": 2,
    "kind": "scenario",
    "name": "blocks-if-else",
    "revision": 1,
    "description": "Sample of the tree format: if else",
    "inputs": {
      "shop_order_id": {
        "required": true
      },
      "personal_name": {
        "required": true
      },
      "aws_account_id": {
        "required": true
      }
    },
    "stages": [
      {
        "name": "Check",
        "steps": [
          {
            "wait_until": "order-state",
            "until": "$self.output.order_status != ''",
            "every": "15s",
            "timeout": "10m",
            "capture": {
              "order_id": "$self.output.order_id",
              "order_status": "$self.output.order_status"
            }
          },
          {
            "if": "$CTX.order_status == 'ON_HOLD' && $CTX.order_id != ''",
            "then": [
              {
                "do": "order-tasks-resolve",
                "with": {
                  "order_id": "$CTX.order_id"
                }
              }
            ],
            "else": [
              {
                "you": "The order is not on hold: check it by hand, then approve."
              }
            ]
          },
          {
            "do": "queue-send",
            "with": {
              "message": "demo.poll",
              "order_id": "$CTX.order_id"
            }
          }
        ]
      }
    ]
  },
  "blocks-nested": {
    "version": 2,
    "kind": "scenario",
    "name": "blocks-nested",
    "revision": 1,
    "description": "Sample of the tree format: nested",
    "inputs": {
      "shop_order_id": {
        "required": true
      },
      "personal_name": {
        "required": true
      },
      "aws_account_id": {
        "required": true
      }
    },
    "stages": [
      {
        "name": "Route order",
        "steps": [
          {
            "wait_until": "order-state",
            "until": "$self.output.order_status != ''",
            "every": "15s",
            "timeout": "10m",
            "capture": {
              "order_id": "$self.output.order_id",
              "order_status": "$self.output.order_status",
              "review_status": "$self.output.review_status"
            }
          },
          {
            "if": "$CTX.order_status == 'ON_HOLD'",
            "then": [
              {
                "if": "$CTX.review_status == 'PENDING' || $CTX.review_status == 'REVIEWED'",
                "then": [
                  {
                    "do": "order-tasks-resolve",
                    "with": {
                      "order_id": "$CTX.order_id"
                    }
                  }
                ],
                "else": [
                  {
                    "you": "The review is neither pending nor done: check it by hand, then approve."
                  }
                ]
              },
              {
                "do": "order-set-carrier",
                "with": {
                  "order_id": "$CTX.order_id"
                }
              },
              {
                "if": "$CTX.review_status == 'REVIEWED'",
                "then": [
                  {
                    "do": "shipments-regenerate",
                    "with": {
                      "order_id": "$CTX.order_id"
                    }
                  }
                ]
              }
            ],
            "else": [
              {
                "do": "queue-send",
                "with": {
                  "message": "demo.process-order",
                  "order_id": "$CTX.order_id"
                }
              }
            ]
          },
          {
            "do": "queue-send",
            "with": {
              "message": "demo.poll",
              "order_id": "$CTX.order_id"
            }
          }
        ]
      }
    ]
  },
  "blocks-repeat": {
    "version": 2,
    "kind": "scenario",
    "name": "blocks-repeat",
    "revision": 1,
    "description": "Sample of the tree format: repeat",
    "inputs": {
      "shop_order_id": {
        "required": true
      },
      "personal_name": {
        "required": true
      },
      "aws_account_id": {
        "required": true
      }
    },
    "stages": [
      {
        "name": "Poll review",
        "steps": [
          {
            "wait_until": "order-state",
            "until": "$self.output.order_id != ''",
            "every": "15s",
            "timeout": "10m",
            "capture": {
              "order_id": "$self.output.order_id"
            }
          },
          {
            "repeat": {
              "max": 5,
              "until": "$poll.output.review_status == 'APPROVED'",
              "steps": [
                {
                  "do": "queue-send",
                  "with": {
                    "message": "demo.poll",
                    "order_id": "$CTX.order_id"
                  }
                },
                {
                  "wait_until": "order-state",
                  "id": "poll",
                  "until": "$self.output.approval_job_id != ''",
                  "every": "15s",
                  "timeout": "10m"
                }
              ]
            }
          }
        ]
      }
    ]
  },
  "blocks-together": {
    "version": 2,
    "kind": "scenario",
    "name": "blocks-together",
    "revision": 1,
    "description": "Sample of the tree format: together",
    "inputs": {
      "shop_order_id": {
        "required": true
      },
      "personal_name": {
        "required": true
      },
      "aws_account_id": {
        "required": true
      }
    },
    "stages": [
      {
        "name": "Fix shipping",
        "steps": [
          {
            "wait_until": "order-state",
            "until": "$self.output.order_id != ''",
            "every": "15s",
            "timeout": "10m",
            "capture": {
              "order_id": "$self.output.order_id"
            }
          },
          {
            "together": [
              [
                {
                  "do": "order-set-carrier",
                  "with": {
                    "order_id": "$CTX.order_id"
                  }
                }
              ],
              [
                {
                  "do": "shipments-regenerate",
                  "with": {
                    "order_id": "$CTX.order_id"
                  }
                },
                {
                  "do": "shipments-mark-in-transit",
                  "with": {
                    "order_id": "$CTX.order_id"
                  }
                }
              ]
            ]
          },
          {
            "do": "queue-send",
            "with": {
              "message": "demo.process-order",
              "order_id": "$CTX.order_id"
            }
          }
        ]
      }
    ]
  },
  "blocks-wait-include": {
    "version": 2,
    "kind": "scenario",
    "name": "blocks-wait-include",
    "revision": 1,
    "description": "Sample of the tree format: wait include",
    "inputs": {
      "shop_order_id": {
        "required": true
      },
      "personal_name": {
        "required": true
      },
      "aws_account_id": {
        "required": true
      }
    },
    "stages": [
      {
        "name": "Settle",
        "steps": [
          {
            "wait": {
              "duration": "1m"
            }
          },
          {
            "include": "blocks-repeat",
            "with": {
              "shop_order_id": "$INPUTS.shop_order_id",
              "personal_name": "$INPUTS.personal_name",
              "aws_account_id": "$INPUTS.aws_account_id"
            }
          }
        ]
      }
    ]
  },
  "demo-order-roundtrip": {
    "version": 2,
    "kind": "scenario",
    "name": "demo-order-roundtrip",
    "revision": 1,
    "description": "One demo-shop order on a personal stack, from fetch to paid",
    "inputs": {
      "shop_order_id": {
        "required": true,
        "description": "The order to follow, from the shop"
      },
      "shop_id": {
        "default": "shop-0001"
      },
      "channel_id": {
        "default": "channel-0001"
      },
      "lookback_minutes": {
        "type": "integer",
        "default": 60
      },
      "personal_name": {
        "required": true,
        "description": "From the environment's values"
      },
      "aws_account_id": {
        "required": true,
        "description": "From the environment's values"
      }
    },
    "stages": [
      {
        "name": "Fetch order",
        "steps": [
          {
            "do": "queue-send",
            "with": {
              "message": "demo.fetch-orders"
            }
          },
          {
            "wait_until": "order-state",
            "until": "$self.output.order_status == 'ON_HOLD' && $self.output.review_status == 'PENDING'",
            "every": "15s",
            "timeout": "10m",
            "capture": {
              "order_id": "$self.output.order_id"
            }
          }
        ]
      },
      {
        "name": "Review",
        "steps": [
          {
            "do": "queue-send",
            "with": {
              "message": "demo.review-orders",
              "order_id": "$CTX.order_id"
            }
          },
          {
            "wait_until": "order-state",
            "until": "$self.output.review_status == 'REVIEWED' && $self.output.payment_status == 'CONFIRMED' && $self.output.open_tasks > 0",
            "every": "15s",
            "timeout": "10m"
          }
        ]
      },
      {
        "name": "Switch carrier",
        "steps": [
          {
            "do": "order-set-carrier",
            "with": {
              "order_id": "$CTX.order_id"
            }
          },
          {
            "do": "order-tasks-resolve",
            "with": {
              "order_id": "$CTX.order_id"
            }
          },
          {
            "do": "shipments-regenerate",
            "with": {
              "order_id": "$CTX.order_id"
            }
          },
          {
            "do": "queue-send",
            "with": {
              "message": "demo.process-order",
              "order_id": "$CTX.order_id"
            }
          },
          {
            "wait_until": "order-state",
            "until": "$self.output.order_status == 'PROCESSED'",
            "every": "15s",
            "timeout": "10m"
          }
        ]
      },
      {
        "name": "Dispatch",
        "steps": [
          {
            "do": "shipments-mark-in-transit",
            "with": {
              "order_id": "$CTX.order_id"
            }
          },
          {
            "wait_until": "order-state",
            "until": "$self.output.invoice_status == 'CREATED'",
            "every": "15s",
            "timeout": "10m",
            "capture": {
              "invoice_number": "$self.output.invoice_number"
            }
          }
        ]
      },
      {
        "name": "Invoice PDF",
        "steps": [
          {
            "you": "Render the PDF of invoice $CTX.invoice_number by hand, then approve."
          }
        ]
      },
      {
        "name": "Send invoice",
        "steps": [
          {
            "do": "queue-send",
            "with": {
              "message": "demo.invoice",
              "order_id": "$CTX.order_id"
            }
          },
          {
            "wait_until": "order-state",
            "until": "$self.output.invoice_status == 'SENT' && $self.output.invoice_update_job_id != ''",
            "every": "15s",
            "timeout": "10m"
          }
        ]
      },
      {
        "name": "Approval",
        "steps": [
          {
            "do": "queue-send",
            "with": {
              "message": "demo.poll",
              "order_id": "$CTX.order_id"
            }
          },
          {
            "wait_until": "order-state",
            "until": "$self.output.approval_job_id != ''",
            "every": "15s",
            "timeout": "10m"
          },
          {
            "do": "queue-send",
            "with": {
              "message": "demo.poll",
              "order_id": "$CTX.order_id"
            }
          },
          {
            "wait_until": "order-state",
            "until": "$self.output.review_status == 'APPROVED'",
            "every": "15s",
            "timeout": "10m"
          }
        ]
      },
      {
        "name": "Payment",
        "steps": [
          {
            "you": "Pay order $CTX.order_id in the payment sandbox, then approve."
          },
          {
            "wait_until": "order-state",
            "until": "$self.output.paid == true && $self.output.payment_job_id != ''",
            "every": "15s",
            "timeout": "15m"
          },
          {
            "do": "queue-send",
            "with": {
              "message": "demo.poll",
              "order_id": "$CTX.order_id"
            }
          },
          {
            "wait_until": "order-state",
            "until": "$self.output.review_status == 'CLOSED'",
            "every": "15s",
            "timeout": "10m"
          }
        ]
      }
    ]
  }
};
