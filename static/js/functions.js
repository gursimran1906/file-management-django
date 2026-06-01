function createInvoiceCostLineRow(options) {
  var isLast = options.isLast !== false;
  var row = document.createElement("div");
  row.setAttribute(
    "class",
    "invoice-cost-line grid grid-cols-1 sm:grid-cols-12 gap-2 items-start"
  );

  var descWrap = document.createElement("div");
  descWrap.setAttribute("class", "sm:col-span-5");
  var descInput = document.createElement("input");
  descInput.setAttribute("type", "text");
  descInput.setAttribute("name", "our_costs_desc[]");
  descInput.setAttribute("class", "form-input invoice-cost-input");
  descInput.setAttribute("placeholder", "Cost description");
  if (options.description) {
    descInput.value = options.description;
  }
  descWrap.appendChild(descInput);

  var amountWrap = document.createElement("div");
  amountWrap.setAttribute("class", "sm:col-span-5");
  var amountInput = document.createElement("input");
  amountInput.setAttribute("type", "number");
  amountInput.setAttribute("step", "0.01");
  amountInput.setAttribute("min", "0");
  amountInput.setAttribute("name", "our_costs[]");
  amountInput.setAttribute("class", "form-input invoice-cost-input");
  amountInput.setAttribute("placeholder", "0.00");
  if (options.required) {
    amountInput.required = true;
  }
  amountWrap.appendChild(amountInput);

  var actionsWrap = document.createElement("div");
  actionsWrap.setAttribute("class", "sm:col-span-2 flex gap-2 invoice-cost-actions");

  if (!options.isFirst) {
    var minusBtn = document.createElement("button");
    minusBtn.setAttribute("type", "button");
    minusBtn.setAttribute("class", "btn-secondary text-xs px-3 invoice-cost-remove");
    minusBtn.setAttribute("aria-label", "Remove cost line");
    minusBtn.textContent = "−";
    minusBtn.addEventListener("click", function () {
      removeInvoiceCostLine(row);
    });
    actionsWrap.appendChild(minusBtn);
  }

  if (isLast) {
    var plusBtn = document.createElement("button");
    plusBtn.setAttribute("type", "button");
    plusBtn.setAttribute("class", "btn-secondary text-xs px-3");
    plusBtn.setAttribute("id", "add_more_fields_inv");
    plusBtn.setAttribute("aria-label", "Add cost line");
    plusBtn.textContent = "+";
    plusBtn.addEventListener("click", function () {
      addFieldsInvoice("our_costs_row");
    });
    actionsWrap.appendChild(plusBtn);
  }

  row.appendChild(descWrap);
  row.appendChild(amountWrap);
  row.appendChild(actionsWrap);
  return row;
}

function ensureInvoiceCostAddButton() {
  var container = document.getElementById("our_costs_row");
  if (!container) return;

  var lines = container.querySelectorAll(".invoice-cost-line");
  lines.forEach(function (line, index) {
    var actions = line.querySelector(".invoice-cost-actions");
    if (!actions) return;

    var existingPlus = actions.querySelector("#add_more_fields_inv");
    if (existingPlus) {
      existingPlus.removeAttribute("id");
    }

    var isLast = index === lines.length - 1;
    var hasPlus = actions.querySelector("[aria-label='Add cost line']");
    var hasMinus = actions.querySelector(".invoice-cost-remove");

    if (!hasMinus && index > 0) {
      var minusBtn = document.createElement("button");
      minusBtn.setAttribute("type", "button");
      minusBtn.setAttribute("class", "btn-secondary text-xs px-3 invoice-cost-remove");
      minusBtn.setAttribute("aria-label", "Remove cost line");
      minusBtn.textContent = "−";
      minusBtn.addEventListener("click", function () {
        removeInvoiceCostLine(line);
      });
      actions.insertBefore(minusBtn, actions.firstChild);
    }

    if (isLast && !hasPlus) {
      var plusBtn = document.createElement("button");
      plusBtn.setAttribute("type", "button");
      plusBtn.setAttribute("class", "btn-secondary text-xs px-3");
      plusBtn.setAttribute("id", "add_more_fields_inv");
      plusBtn.setAttribute("aria-label", "Add cost line");
      plusBtn.textContent = "+";
      plusBtn.addEventListener("click", function () {
        addFieldsInvoice("our_costs_row");
      });
      actions.appendChild(plusBtn);
    } else if (!isLast && hasPlus) {
      hasPlus.remove();
    }
  });
}

function addFieldsInvoice(id) {
  var container = document.getElementById(id);
  if (!container) return;

  var addButton = document.getElementById("add_more_fields_inv");
  if (!addButton) return;

  var currentRow = addButton.closest(".invoice-cost-line");
  if (currentRow) {
    addButton.removeAttribute("id");
    if (!currentRow.querySelector(".invoice-cost-remove")) {
      var actions = addButton.parentNode;
      var minusBtn = document.createElement("button");
      minusBtn.setAttribute("type", "button");
      minusBtn.setAttribute("class", "btn-secondary text-xs px-3 invoice-cost-remove");
      minusBtn.setAttribute("aria-label", "Remove cost line");
      minusBtn.textContent = "−";
      minusBtn.addEventListener("click", function () {
        removeInvoiceCostLine(currentRow);
      });
      actions.insertBefore(minusBtn, addButton);
    }
    addButton.remove();
  }

  container.appendChild(createInvoiceCostLineRow({ isFirst: false, isLast: true }));
  if (typeof window.updateInvoiceCostPreview === "function") {
    window.updateInvoiceCostPreview();
  }
}

function removeInvoiceCostLine(row) {
  if (!row || !row.parentNode) return;
  row.parentNode.removeChild(row);
  ensureInvoiceCostAddButton();
  if (typeof window.updateInvoiceCostPreview === "function") {
    window.updateInvoiceCostPreview();
  }
}

function removeField(minusElm) {
  if (!minusElm) return;
  var row = minusElm.closest(".invoice-cost-line");
  if (row) {
    removeInvoiceCostLine(row);
    return;
  }
  if (minusElm.parentNode && minusElm.parentNode.parentNode) {
    minusElm.parentNode.parentNode.remove();
  }
}

function addFieldsUndertaking(id) {
  var container = document.getElementById(id);

  var input = document.createElement("textarea");
  input.type = "text";
  input.className = "form-input mt-2";
  input.name = "undertakings[]";

  var inputDiv = document.createElement("div");
  inputDiv.className = "col-span-10";

  inputDiv.appendChild(input);

  var fieldDiv = document.createElement("div");
  fieldDiv.className = "grid grid-cols-12 gap-2";

  fieldDiv.appendChild(inputDiv);

  var deleteButton = document.createElement("span");
  deleteButton.type = "button";
  deleteButton.className = "btn-danger self-center";
  deleteButton.innerHTML = "-";
  deleteButton.onclick = function () {
    container.removeChild(fieldDiv);
  };

  var deleteBtnDiv = document.createElement("div");
  deleteBtnDiv.className = "col-span-2 mt-2";
  deleteBtnDiv.appendChild(deleteButton);

  fieldDiv.appendChild(deleteBtnDiv);

  container.appendChild(fieldDiv);
}

function toggleForm(divName) {
  const element = document.getElementById("inputNew" + divName);
  checkValue = document.getElementById(divName + "List");
  const inputs = element.getElementsByTagName("input");
  if (checkValue.value == "-1") {
    element.style.display = "block";
    for (let i = 0; i < inputs.length; i++) {
      inputs[i].disabled = false;
    }
  } else {
    element.style.display = "none";
    for (let i = 0; i < inputs.length; i++) {
      inputs[i].disabled = true;
    }
  }
}
