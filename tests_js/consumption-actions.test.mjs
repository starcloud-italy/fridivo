import assert from "node:assert/strict";
import test from "node:test";

import {
  CONSUMPTION_ACTIONS,
  consumptionEventPayload,
  inventoryAfterConsumption
} from "../frontend/consumption-actions.mjs";
import { visibleInventoryItems } from "../frontend/expiry.mjs";


test("priority cards expose the existing consumption event types", () => {
  assert.deepEqual(
    CONSUMPTION_ACTIONS.map((action) => action.type),
    ["CONSUMED", "FINISHED", "DISCARDED"]
  );
  assert.deepEqual(
    CONSUMPTION_ACTIONS.map((action) => action.translationKey),
    ["consumption.consumed", "consumption.finished", "consumption.discarded"]
  );
});

test("CONSUMED and DISCARDED preserve quantity while FINISHED uses backend semantics", () => {
  assert.deepEqual(consumptionEventPayload("item-1", "CONSUMED", 2), {
    inventory_item_id: "item-1",
    event_type: "CONSUMED",
    quantity: 2
  });
  assert.deepEqual(consumptionEventPayload("item-1", "DISCARDED", 3), {
    inventory_item_id: "item-1",
    event_type: "DISCARDED",
    quantity: 3
  });
  assert.deepEqual(consumptionEventPayload("item-1", "FINISHED", 1), {
    inventory_item_id: "item-1",
    event_type: "FINISHED"
  });
});

test("the shared inventory update keeps residual quantities and removes finished items", () => {
  const items = [
    { id: "item-1", quantity: 3, product_name: "Milk" },
    { id: "item-2", quantity: 1, product_name: "Yogurt" }
  ];

  assert.deepEqual(inventoryAfterConsumption(items, "item-1", 1), [
    { id: "item-1", quantity: 2, product_name: "Milk" },
    items[1]
  ]);
  assert.deepEqual(inventoryAfterConsumption(items, "item-2", 1), [items[0]]);
  assert.equal(inventoryAfterConsumption(items, "missing", 1), items);
});

test("all priority actions keep refreshed Consume First and Inventory projections coherent", () => {
  const initial = [
    { id: "milk", quantity: 2 },
    { id: "yogurt", quantity: 1 },
    { id: "pasta", quantity: 3 }
  ];

  for (const action of ["CONSUMED", "FINISHED", "DISCARDED"]) {
    const quantity = action === "CONSUMED" ? 1 : 2;
    const updatedInventory = inventoryAfterConsumption(initial, "milk", quantity);
    const refreshedPriorities = action === "CONSUMED"
      ? [updatedInventory[0], updatedInventory[1]]
      : [updatedInventory[0]];

    assert.deepEqual(
      visibleInventoryItems("PLUS", updatedInventory, refreshedPriorities),
      action === "CONSUMED" ? [updatedInventory[2]] : [updatedInventory[1]]
    );
  }
});
