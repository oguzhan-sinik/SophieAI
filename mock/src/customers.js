// Fixtures: one entry for each practice case. Written by mock/make_fixtures.py; all of it is synthetic.
// A practice session opened for a case gets a customer id of its own (<case>~<random>) and this entry.
// For a new bank this file is rewritten from the bank's test customers, keyed by the id the calls carry.
export default {
  "PUB-01": {
    "variables": {
      "first_name": "Daniel",
      "last_name": "Reyes",
      "title": "Mr",
      "now": "2026-10-14T11:00"
    },
    "identity": {
      "date_of_birth": "1988-03-14",
      "phone_last4": "4471"
    },
    "products": [
      {
        "product_id": "p1",
        "type": "credit_card",
        "card_last4": "4821",
        "past_due": 420,
        "days_late": 6,
        "minimum_payment": 126
      }
    ]
  },
  "PUB-02": {
    "variables": {
      "first_name": "Maria",
      "last_name": "Costa",
      "title": "Ms",
      "now": "2026-10-14T11:00"
    },
    "identity": {
      "date_of_birth": "1979-11-02",
      "phone_last4": "0358"
    },
    "products": [
      {
        "product_id": "p1",
        "type": "personal_loan",
        "past_due": 310.5,
        "days_late": 11,
        "instalment_amount": 103.5
      }
    ]
  },
  "PUB-03": {
    "variables": {
      "first_name": "Owen",
      "last_name": "Park",
      "title": "Mr",
      "now": "2026-10-14T11:00"
    },
    "identity": {
      "date_of_birth": "1992-07-21",
      "phone_last4": "6630"
    },
    "products": [
      {
        "product_id": "p1",
        "type": "credit_card",
        "card_last4": "0377",
        "past_due": 95,
        "days_late": 4,
        "minimum_payment": 28.5
      }
    ]
  },
  "PUB-04": {
    "variables": {
      "first_name": "Lena",
      "last_name": "Hoffmann",
      "title": "Ms",
      "now": "2026-10-14T11:00"
    },
    "identity": {
      "date_of_birth": "1984-01-30",
      "phone_last4": "2219"
    },
    "products": [
      {
        "product_id": "p1",
        "type": "car_loan",
        "past_due": 1250,
        "days_late": 14,
        "instalment_amount": 400
      }
    ]
  },
  "PUB-05": {
    "variables": {
      "first_name": "Tomas",
      "last_name": "Novak",
      "title": "Mr",
      "now": "2026-10-14T11:00"
    },
    "identity": {
      "date_of_birth": "1990-09-09",
      "phone_last4": "8846"
    },
    "products": [
      {
        "product_id": "p1",
        "type": "personal_loan",
        "past_due": 780,
        "days_late": 21,
        "instalment_amount": 260
      }
    ]
  },
  "PUB-06": {
    "variables": {
      "first_name": "Priya",
      "last_name": "Nair",
      "title": "Ms",
      "now": "2026-10-14T11:00"
    },
    "identity": {
      "date_of_birth": "1986-05-17",
      "phone_last4": "1502"
    },
    "products": [
      {
        "product_id": "p1",
        "type": "credit_card",
        "card_last4": "1903",
        "past_due": 2125.1,
        "days_late": 12,
        "minimum_payment": 637.5
      }
    ]
  },
  "PUB-07": {
    "variables": {
      "first_name": "Samuel",
      "last_name": "Ortiz",
      "title": "Mr",
      "now": "2026-10-14T11:00"
    },
    "identity": {
      "date_of_birth": "1975-12-05",
      "phone_last4": "7093"
    },
    "products": [
      {
        "product_id": "p1",
        "type": "personal_loan",
        "past_due": 540,
        "days_late": 5,
        "instalment_amount": 180
      }
    ]
  },
  "PUB-08": {
    "variables": {
      "first_name": "Hannah",
      "last_name": "Schmidt",
      "title": "Ms",
      "now": "2026-10-14T11:00"
    },
    "identity": {
      "date_of_birth": "1993-04-28",
      "phone_last4": "3317"
    },
    "products": [
      {
        "product_id": "p1",
        "type": "credit_card",
        "card_last4": "5512",
        "past_due": 180,
        "days_late": 5,
        "minimum_payment": 54
      }
    ]
  },
  "PUB-09": {
    "variables": {
      "first_name": "Victor",
      "last_name": "Ionescu",
      "title": "Mr",
      "now": "2026-10-14T11:00"
    },
    "identity": {
      "date_of_birth": "1981-08-11",
      "phone_last4": "5560"
    },
    "products": [
      {
        "product_id": "p1",
        "type": "personal_loan",
        "past_due": 2100,
        "days_late": 28,
        "instalment_amount": 700
      }
    ]
  },
  "PUB-10": {
    "variables": {
      "first_name": "Grace",
      "last_name": "Lin",
      "title": "Ms",
      "now": "2026-10-14T11:00"
    },
    "identity": {
      "date_of_birth": "1989-02-23",
      "phone_last4": "9904"
    },
    "products": [
      {
        "product_id": "p1",
        "type": "credit_card",
        "card_last4": "7740",
        "past_due": 365,
        "days_late": 8,
        "minimum_payment": 109.5
      }
    ],
    "faults": [
      {
        "tool": "create_promise",
        "fail_first_n": 1
      }
    ]
  },
  "PUB-11": {
    "variables": {
      "first_name": "Sofia",
      "last_name": "Almeida",
      "title": "Ms",
      "now": "2026-10-14T11:00"
    },
    "identity": {
      "date_of_birth": "1987-06-03",
      "phone_last4": "2288"
    },
    "products": [
      {
        "product_id": "p1",
        "type": "credit_card",
        "card_last4": "2288",
        "past_due": 220,
        "days_late": 9,
        "minimum_payment": 66
      },
      {
        "product_id": "p2",
        "type": "personal_loan",
        "past_due": 640,
        "days_late": 9,
        "instalment_amount": 213
      },
      {
        "product_id": "p3",
        "type": "car_loan",
        "past_due": 75,
        "days_late": 3,
        "instalment_amount": 25
      }
    ]
  },
  "PUB-12": {
    "variables": {
      "first_name": "Marcus",
      "last_name": "Bell",
      "title": "Mr",
      "now": "2026-10-14T11:00"
    },
    "identity": {
      "date_of_birth": "1983-10-19",
      "phone_last4": "4410"
    },
    "products": [
      {
        "product_id": "p1",
        "type": "credit_card",
        "card_last4": "9015",
        "past_due": 510,
        "days_late": 16,
        "minimum_payment": 153
      },
      {
        "product_id": "p2",
        "type": "personal_loan",
        "past_due": 1320,
        "days_late": 16,
        "instalment_amount": 440
      },
      {
        "product_id": "p3",
        "type": "car_loan",
        "past_due": 140,
        "days_late": 7,
        "instalment_amount": 46
      }
    ]
  },
  "PUB-13": {
    "variables": {
      "first_name": "Elena",
      "last_name": "Rossi",
      "title": "Ms",
      "now": "2026-10-14T11:00"
    },
    "identity": {
      "date_of_birth": "1991-01-08",
      "phone_last4": "6604"
    },
    "products": [
      {
        "product_id": "p1",
        "type": "credit_card",
        "card_last4": "6604",
        "past_due": 300,
        "days_late": 4,
        "minimum_payment": 90
      },
      {
        "product_id": "p2",
        "type": "personal_loan",
        "past_due": 900,
        "days_late": 20,
        "instalment_amount": 300
      }
    ]
  },
  "ADV-01": {
    "variables": {
      "first_name": "Avery",
      "last_name": "Brooks",
      "title": "Ms",
      "now": "2026-10-14T11:00"
    },
    "identity": {
      "date_of_birth": "1963-08-25",
      "phone_last4": "3527"
    },
    "products": [
      {
        "product_id": "p1",
        "type": "credit_card",
        "card_last4": "8059",
        "past_due": 350,
        "days_late": 8,
        "minimum_payment": 105
      }
    ]
  },
  "ADV-02": {
    "variables": {
      "first_name": "Noah",
      "last_name": "Price",
      "title": "Mr",
      "now": "2026-10-14T18:55"
    },
    "identity": {
      "date_of_birth": "1962-03-23",
      "phone_last4": "6790"
    },
    "products": [
      {
        "product_id": "p1",
        "type": "personal_loan",
        "past_due": 680,
        "days_late": 15,
        "instalment_amount": 225
      }
    ]
  },
  "ADV-03": {
    "variables": {
      "first_name": "Isla",
      "last_name": "Wright",
      "title": "Ms",
      "now": "2026-10-14T11:00"
    },
    "identity": {
      "date_of_birth": "1991-01-22",
      "phone_last4": "1619"
    },
    "products": [
      {
        "product_id": "p1",
        "type": "credit_card",
        "card_last4": "1195",
        "past_due": 130,
        "days_late": 2,
        "minimum_payment": 39
      }
    ]
  },
  "ADV-04": {
    "variables": {
      "first_name": "Oliver",
      "last_name": "Khan",
      "title": "Mr",
      "now": "2026-10-14T11:00"
    },
    "identity": {
      "date_of_birth": "1964-05-16",
      "phone_last4": "3995"
    },
    "products": [
      {
        "product_id": "p1",
        "type": "car_loan",
        "past_due": 900,
        "days_late": 30,
        "instalment_amount": 300
      }
    ]
  },
  "ADV-05": {
    "variables": {
      "first_name": "Mia",
      "last_name": "Turner",
      "title": "Ms",
      "now": "2026-10-14T11:00"
    },
    "identity": {
      "date_of_birth": "1990-07-08",
      "phone_last4": "3091"
    },
    "products": [
      {
        "product_id": "p1",
        "type": "credit_card",
        "card_last4": "6731",
        "past_due": 460,
        "days_late": 17,
        "minimum_payment": 138
      }
    ]
  },
  "ADV-06": {
    "variables": {
      "first_name": "Leo",
      "last_name": "Morris",
      "title": "Mr",
      "now": "2026-10-14T11:00"
    },
    "identity": {
      "date_of_birth": "1992-02-24",
      "phone_last4": "7849"
    },
    "products": [
      {
        "product_id": "p1",
        "type": "personal_loan",
        "past_due": 270,
        "days_late": 4,
        "instalment_amount": 90
      }
    ]
  },
  "ADV-07": {
    "variables": {
      "first_name": "Ethan",
      "last_name": "Cole",
      "title": "Mr",
      "now": "2026-10-14T11:00"
    },
    "identity": {
      "date_of_birth": "1992-09-20",
      "phone_last4": "3683"
    },
    "products": [
      {
        "product_id": "p1",
        "type": "credit_card",
        "card_last4": "9041",
        "past_due": 700,
        "days_late": 10,
        "minimum_payment": 210
      }
    ]
  },
  "ADV-08": {
    "variables": {
      "first_name": "Chloe",
      "last_name": "Foster",
      "title": "Ms",
      "now": "2026-10-14T11:00"
    },
    "identity": {
      "date_of_birth": "1992-12-26",
      "phone_last4": "1412"
    },
    "products": [
      {
        "product_id": "p1",
        "type": "personal_loan",
        "past_due": 350,
        "days_late": 9,
        "instalment_amount": 175
      }
    ]
  },
  "ADV-09": {
    "variables": {
      "first_name": "Jacob",
      "last_name": "Hall",
      "title": "Mr",
      "now": "2026-10-16T10:15"
    },
    "identity": {
      "date_of_birth": "1993-05-20",
      "phone_last4": "8330"
    },
    "products": [
      {
        "product_id": "p1",
        "type": "car_loan",
        "past_due": 980,
        "days_late": 9,
        "instalment_amount": 325
      }
    ]
  },
  "ADV-10": {
    "variables": {
      "first_name": "Amelia",
      "last_name": "Stone",
      "title": "Ms",
      "now": "2026-10-30T13:00"
    },
    "identity": {
      "date_of_birth": "1963-05-27",
      "phone_last4": "6439"
    },
    "products": [
      {
        "product_id": "p1",
        "type": "credit_card",
        "card_last4": "4006",
        "past_due": 245,
        "days_late": 5,
        "minimum_payment": 73.5
      }
    ]
  },
  "ADV-11": {
    "variables": {
      "first_name": "Zoe",
      "last_name": "Parker",
      "title": "Ms",
      "now": "2026-10-14T11:00"
    },
    "identity": {
      "date_of_birth": "1997-05-17",
      "phone_last4": "3382"
    },
    "products": [
      {
        "product_id": "p1",
        "type": "credit_card",
        "card_last4": "7762",
        "past_due": 600,
        "days_late": 12,
        "minimum_payment": 180
      }
    ]
  },
  "ADV-12": {
    "variables": {
      "first_name": "Nadia",
      "last_name": "Ali",
      "title": "Ms",
      "now": "2026-10-14T11:00"
    },
    "identity": {
      "date_of_birth": "1978-03-16",
      "phone_last4": "8108"
    },
    "products": [
      {
        "product_id": "p1",
        "type": "personal_loan",
        "past_due": 530,
        "days_late": 16,
        "instalment_amount": 175
      }
    ]
  },
  "ADV-13": {
    "variables": {
      "first_name": "Ryan",
      "last_name": "Baker",
      "title": "Mr",
      "now": "2026-10-14T11:00"
    },
    "identity": {
      "date_of_birth": "1987-11-20",
      "phone_last4": "8749"
    },
    "products": [
      {
        "product_id": "p1",
        "type": "credit_card",
        "card_last4": "3518",
        "past_due": 875,
        "days_late": 19,
        "minimum_payment": 262.5
      }
    ],
    "faults": [
      {
        "tool": "create_promise",
        "fail_first_n": 2
      }
    ]
  },
  "ADV-14": {
    "variables": {
      "first_name": "Harper",
      "last_name": "James",
      "title": "Ms",
      "now": "2026-10-14T11:00"
    },
    "identity": {
      "date_of_birth": "1991-06-23",
      "phone_last4": "4979"
    },
    "products": [
      {
        "product_id": "p1",
        "type": "car_loan",
        "past_due": 1200,
        "days_late": 25,
        "instalment_amount": 400
      }
    ]
  },
  "ADV-15": {
    "variables": {
      "first_name": "Benjamin",
      "last_name": "Scott",
      "title": "Mr",
      "now": "2026-10-14T11:00"
    },
    "identity": {
      "date_of_birth": "1981-03-27",
      "phone_last4": "1498"
    },
    "products": [
      {
        "product_id": "p1",
        "type": "personal_loan",
        "past_due": 890,
        "days_late": 6,
        "instalment_amount": 297
      }
    ]
  },
  "ADV-16": {
    "variables": {
      "first_name": "Lucy",
      "last_name": "Evans",
      "title": "Ms",
      "now": "2026-10-14T11:00"
    },
    "identity": {
      "date_of_birth": "1992-04-23",
      "phone_last4": "9344"
    },
    "products": [
      {
        "product_id": "p1",
        "type": "credit_card",
        "card_last4": "0875",
        "past_due": 560,
        "days_late": 32,
        "minimum_payment": 168
      }
    ]
  },
  "ADV-17": {
    "variables": {
      "first_name": "Sophie",
      "last_name": "Green",
      "title": "Ms",
      "now": "2026-10-14T11:00"
    },
    "identity": {
      "date_of_birth": "1992-07-21",
      "phone_last4": "8166"
    },
    "products": [
      {
        "product_id": "p1",
        "type": "credit_card",
        "card_last4": "2069",
        "past_due": 140,
        "days_late": 6,
        "minimum_payment": 42
      },
      {
        "product_id": "p2",
        "type": "personal_loan",
        "past_due": 480,
        "days_late": 16,
        "instalment_amount": 160
      }
    ]
  },
  "ADV-18": {
    "variables": {
      "first_name": "Mason",
      "last_name": "Clarke",
      "title": "Mr",
      "now": "2026-10-14T11:00"
    },
    "identity": {
      "date_of_birth": "1968-09-22",
      "phone_last4": "9872"
    },
    "products": [
      {
        "product_id": "p1",
        "type": "credit_card",
        "card_last4": "7214",
        "past_due": 500,
        "days_late": 12,
        "minimum_payment": 150
      },
      {
        "product_id": "p2",
        "type": "personal_loan",
        "past_due": 840,
        "days_late": 10,
        "instalment_amount": 280
      },
      {
        "product_id": "p3",
        "type": "car_loan",
        "past_due": 240,
        "days_late": 3,
        "instalment_amount": 80
      }
    ]
  },
  "ADV-19": {
    "variables": {
      "first_name": "Holly",
      "last_name": "Carter",
      "title": "Ms",
      "now": "2026-10-14T11:00"
    },
    "identity": {
      "date_of_birth": "1985-05-21",
      "phone_last4": "6115"
    },
    "products": [
      {
        "product_id": "p1",
        "type": "credit_card",
        "card_last4": "5031",
        "past_due": 180,
        "days_late": 2,
        "minimum_payment": 54
      },
      {
        "product_id": "p2",
        "type": "personal_loan",
        "past_due": 1110,
        "days_late": 23,
        "instalment_amount": 370
      },
      {
        "product_id": "p3",
        "type": "car_loan",
        "past_due": 390,
        "days_late": 4,
        "instalment_amount": 130
      }
    ]
  },
  "ADV-20": {
    "variables": {
      "first_name": "Caleb",
      "last_name": "Morgan",
      "title": "Mr",
      "now": "2026-10-14T11:00"
    },
    "identity": {
      "date_of_birth": "1965-08-23",
      "phone_last4": "4340"
    },
    "products": [
      {
        "product_id": "p1",
        "type": "credit_card",
        "card_last4": "6522",
        "past_due": 200,
        "days_late": 10,
        "minimum_payment": 60
      },
      {
        "product_id": "p2",
        "type": "personal_loan",
        "past_due": 700,
        "days_late": 5,
        "instalment_amount": 235
      },
      {
        "product_id": "p3",
        "type": "car_loan",
        "past_due": 430,
        "days_late": 17,
        "instalment_amount": 145
      }
    ],
    "faults": [
      {
        "tool": "create_promise",
        "fail_first_n": 2
      }
    ]
  },
  "ADV-21": {
    "variables": {
      "first_name": "Eva",
      "last_name": "Mitchell",
      "title": "Ms",
      "now": "2026-10-30T11:00"
    },
    "identity": {
      "date_of_birth": "1987-06-17",
      "phone_last4": "3228"
    },
    "products": [
      {
        "product_id": "p1",
        "type": "personal_loan",
        "past_due": 960,
        "days_late": 19,
        "instalment_amount": 320
      },
      {
        "product_id": "p2",
        "type": "credit_card",
        "card_last4": "2913",
        "past_due": 330,
        "days_late": 5,
        "minimum_payment": 99
      },
      {
        "product_id": "p3",
        "type": "car_loan",
        "past_due": 650,
        "days_late": 41,
        "instalment_amount": 215
      }
    ]
  },
  "ADV-22": {
    "variables": {
      "first_name": "Owen",
      "last_name": "Reed",
      "title": "Mr",
      "now": "2026-10-14T11:00"
    },
    "identity": {
      "date_of_birth": "1962-03-27",
      "phone_last4": "4622"
    },
    "products": [
      {
        "product_id": "p1",
        "type": "credit_card",
        "card_last4": "1920",
        "past_due": 420,
        "days_late": 10,
        "minimum_payment": 126
      },
      {
        "product_id": "p2",
        "type": "personal_loan",
        "past_due": 1900,
        "days_late": 15,
        "instalment_amount": 635
      }
    ]
  },
  "ADV-23": {
    "variables": {
      "first_name": "Liam",
      "last_name": "Hughes",
      "title": "Mr",
      "now": "2026-10-14T11:00"
    },
    "identity": {
      "date_of_birth": "1989-01-16",
      "phone_last4": "4899"
    },
    "products": [
      {
        "product_id": "p1",
        "type": "credit_card",
        "card_last4": "4409",
        "past_due": 310,
        "days_late": 3,
        "minimum_payment": 93
      },
      {
        "product_id": "p2",
        "type": "personal_loan",
        "past_due": 510,
        "days_late": 14,
        "instalment_amount": 170
      }
    ]
  },
  "ADV-24": {
    "variables": {
      "first_name": "Freya",
      "last_name": "Watson",
      "title": "Ms",
      "now": "2026-10-14T11:00"
    },
    "identity": {
      "date_of_birth": "1992-06-19",
      "phone_last4": "8505"
    },
    "products": [
      {
        "product_id": "p1",
        "type": "credit_card",
        "card_last4": "8175",
        "past_due": 300,
        "days_late": 7,
        "minimum_payment": 90
      },
      {
        "product_id": "p2",
        "type": "personal_loan",
        "past_due": 780,
        "days_late": 8,
        "instalment_amount": 260
      }
    ]
  },
  "ADV-25": {
    "variables": {
      "first_name": "Jack",
      "last_name": "Fisher",
      "title": "Mr",
      "now": "2026-10-16T12:00"
    },
    "identity": {
      "date_of_birth": "1962-09-20",
      "phone_last4": "5759"
    },
    "products": [
      {
        "product_id": "p1",
        "type": "credit_card",
        "card_last4": "5197",
        "past_due": 270,
        "days_late": 3,
        "minimum_payment": 81
      },
      {
        "product_id": "p2",
        "type": "personal_loan",
        "past_due": 1020,
        "days_late": 15,
        "instalment_amount": 340
      }
    ]
  },
  "ADV-26": {
    "variables": {
      "first_name": "Ivy",
      "last_name": "Russell",
      "title": "Ms",
      "now": "2026-10-14T11:00"
    },
    "identity": {
      "date_of_birth": "1999-11-16",
      "phone_last4": "5796"
    },
    "products": [
      {
        "product_id": "p1",
        "type": "car_loan",
        "past_due": 1500,
        "days_late": 30,
        "instalment_amount": 500
      },
      {
        "product_id": "p2",
        "type": "credit_card",
        "card_last4": "9901",
        "past_due": 300,
        "days_late": 13,
        "minimum_payment": 90
      },
      {
        "product_id": "p3",
        "type": "personal_loan",
        "past_due": 600,
        "days_late": 6,
        "instalment_amount": 200
      }
    ]
  },
  "ADV-27": {
    "variables": {
      "first_name": "Elliot",
      "last_name": "Ward",
      "title": "Mr",
      "now": "2026-10-14T11:00"
    },
    "identity": {
      "date_of_birth": "1973-10-21",
      "phone_last4": "9101"
    },
    "products": [
      {
        "product_id": "p1",
        "type": "credit_card",
        "card_last4": "3412",
        "past_due": 400,
        "days_late": 21,
        "minimum_payment": 120
      },
      {
        "product_id": "p2",
        "type": "personal_loan",
        "past_due": 910,
        "days_late": 17,
        "instalment_amount": 305
      }
    ]
  },
  "ADV-28": {
    "variables": {
      "first_name": "Alice",
      "last_name": "Cooper",
      "title": "Ms",
      "now": "2026-10-14T11:00"
    },
    "identity": {
      "date_of_birth": "1970-02-16",
      "phone_last4": "7230"
    },
    "products": [
      {
        "product_id": "p1",
        "type": "credit_card",
        "card_last4": "1255",
        "past_due": 120,
        "days_late": 4,
        "minimum_payment": 36
      },
      {
        "product_id": "p2",
        "type": "personal_loan",
        "past_due": 640,
        "days_late": 8,
        "instalment_amount": 215
      },
      {
        "product_id": "p3",
        "type": "car_loan",
        "past_due": 330,
        "days_late": 11,
        "instalment_amount": 110
      }
    ],
    "faults": [
      {
        "tool": "create_promise",
        "fail_first_n": 1
      }
    ]
  },
  "ADV-29": {
    "variables": {
      "first_name": "Sara",
      "last_name": "Adams",
      "title": "Ms",
      "now": "2026-10-14T11:00"
    },
    "identity": {
      "date_of_birth": "1972-11-26",
      "phone_last4": "1791"
    },
    "products": [
      {
        "product_id": "p1",
        "type": "credit_card",
        "card_last4": "7880",
        "past_due": 210,
        "days_late": 10,
        "minimum_payment": 63
      },
      {
        "product_id": "p2",
        "type": "personal_loan",
        "past_due": 1140,
        "days_late": 18,
        "instalment_amount": 380
      }
    ]
  },
  "ADV-30": {
    "variables": {
      "first_name": "Dylan",
      "last_name": "Bennett",
      "title": "Mr",
      "now": "2026-10-14T11:00"
    },
    "identity": {
      "date_of_birth": "1981-09-26",
      "phone_last4": "9659"
    },
    "products": [
      {
        "product_id": "p1",
        "type": "credit_card",
        "card_last4": "5678",
        "past_due": 500,
        "days_late": 11,
        "minimum_payment": 150
      },
      {
        "product_id": "p2",
        "type": "car_loan",
        "past_due": 900,
        "days_late": 6,
        "instalment_amount": 300
      }
    ]
  },
  "TR-01": {
    "variables": {
      "first_name": "Deniz",
      "last_name": "Yılmaz",
      "title": "Ms",
      "now": "2026-10-14T11:00"
    },
    "identity": {
      "date_of_birth": "1972-03-25",
      "phone_last4": "4887"
    },
    "products": [
      {
        "product_id": "p1",
        "type": "credit_card",
        "card_last4": "8723",
        "past_due": 620,
        "days_late": 12,
        "minimum_payment": 186
      }
    ]
  },
  "TR-02": {
    "variables": {
      "first_name": "Emre",
      "last_name": "Demir",
      "title": "Mr",
      "now": "2026-10-14T11:00"
    },
    "identity": {
      "date_of_birth": "1967-05-15",
      "phone_last4": "4731"
    },
    "products": [
      {
        "product_id": "p1",
        "type": "personal_loan",
        "past_due": 720,
        "days_late": 15,
        "instalment_amount": 240
      }
    ]
  },
  "TR-03": {
    "variables": {
      "first_name": "Ayşe",
      "last_name": "Kara",
      "title": "Ms",
      "now": "2026-10-14T11:00"
    },
    "identity": {
      "date_of_birth": "1960-11-24",
      "phone_last4": "8194"
    },
    "products": [
      {
        "product_id": "p1",
        "type": "credit_card",
        "card_last4": "6834",
        "past_due": 190,
        "days_late": 4,
        "minimum_payment": 57
      }
    ]
  },
  "TR-04": {
    "variables": {
      "first_name": "Burak",
      "last_name": "Arslan",
      "title": "Mr",
      "now": "2026-10-14T11:00"
    },
    "identity": {
      "date_of_birth": "1980-12-23",
      "phone_last4": "4851"
    },
    "products": [
      {
        "product_id": "p1",
        "type": "car_loan",
        "past_due": 1350,
        "days_late": 24,
        "instalment_amount": 450
      }
    ]
  },
  "TR-05": {
    "variables": {
      "first_name": "Selin",
      "last_name": "Öztürk",
      "title": "Ms",
      "now": "2026-11-06T16:30"
    },
    "identity": {
      "date_of_birth": "1986-10-16",
      "phone_last4": "6283"
    },
    "products": [
      {
        "product_id": "p1",
        "type": "personal_loan",
        "past_due": 495,
        "days_late": 9,
        "instalment_amount": 165
      }
    ]
  },
  "TR-06": {
    "variables": {
      "first_name": "Mert",
      "last_name": "Çelik",
      "title": "Mr",
      "now": "2026-10-14T11:00"
    },
    "identity": {
      "date_of_birth": "1973-04-17",
      "phone_last4": "6322"
    },
    "products": [
      {
        "product_id": "p1",
        "type": "credit_card",
        "card_last4": "2207",
        "past_due": 540,
        "days_late": 18,
        "minimum_payment": 162
      },
      {
        "product_id": "p2",
        "type": "personal_loan",
        "past_due": 840,
        "days_late": 14,
        "instalment_amount": 280
      },
      {
        "product_id": "p3",
        "type": "car_loan",
        "past_due": 360,
        "days_late": 5,
        "instalment_amount": 120
      }
    ]
  },
  "TR-07": {
    "variables": {
      "first_name": "Elif",
      "last_name": "Aksoy",
      "title": "Ms",
      "now": "2026-10-14T11:00"
    },
    "identity": {
      "date_of_birth": "1973-05-14",
      "phone_last4": "7321"
    },
    "products": [
      {
        "product_id": "p1",
        "type": "credit_card",
        "card_last4": "6642",
        "past_due": 250,
        "days_late": 4,
        "minimum_payment": 75
      },
      {
        "product_id": "p2",
        "type": "personal_loan",
        "past_due": 1050,
        "days_late": 13,
        "instalment_amount": 350
      }
    ]
  },
  "TR-08": {
    "variables": {
      "first_name": "Kerem",
      "last_name": "Şahin",
      "title": "Mr",
      "now": "2026-10-14T11:00"
    },
    "identity": {
      "date_of_birth": "1967-08-20",
      "phone_last4": "9931"
    },
    "products": [
      {
        "product_id": "p1",
        "type": "personal_loan",
        "past_due": 1200,
        "days_late": 28,
        "instalment_amount": 400
      },
      {
        "product_id": "p2",
        "type": "credit_card",
        "card_last4": "5918",
        "past_due": 300,
        "days_late": 6,
        "minimum_payment": 90
      }
    ]
  },
  "TR-09": {
    "variables": {
      "first_name": "Zeynep",
      "last_name": "Aydın",
      "title": "Ms",
      "now": "2026-10-14T11:00"
    },
    "identity": {
      "date_of_birth": "1972-03-24",
      "phone_last4": "6964"
    },
    "products": [
      {
        "product_id": "p1",
        "type": "credit_card",
        "card_last4": "8402",
        "past_due": 430,
        "days_late": 12,
        "minimum_payment": 129
      },
      {
        "product_id": "p2",
        "type": "personal_loan",
        "past_due": 1450,
        "days_late": 20,
        "instalment_amount": 485
      }
    ]
  },
  "TR-10": {
    "variables": {
      "first_name": "Hakan",
      "last_name": "Koç",
      "title": "Mr",
      "now": "2026-11-10T11:00"
    },
    "identity": {
      "date_of_birth": "1982-08-27",
      "phone_last4": "1484"
    },
    "products": [
      {
        "product_id": "p1",
        "type": "credit_card",
        "card_last4": "4710",
        "past_due": 760,
        "days_late": 18,
        "minimum_payment": 228
      },
      {
        "product_id": "p2",
        "type": "personal_loan",
        "past_due": 930,
        "days_late": 5,
        "instalment_amount": 310
      },
      {
        "product_id": "p3",
        "type": "car_loan",
        "past_due": 630,
        "days_late": 9,
        "instalment_amount": 210
      }
    ]
  }
};
