function addFieldsInvoice(id) {
  var container = document.getElementById(id);

  var divElmNewRow = document.createElement("div");
  divElmNewRow.setAttribute("class", "grid grid-cols-12 gap-4 mt-2");

  var divElmField = document.createElement("div");
  divElmField.setAttribute("class", "col-span-5");

  var divElmField1 = document.createElement("div");
  divElmField1.setAttribute("class", "col-span-5");

  var divElmFieldSymbol = document.createElement("div");
  divElmFieldSymbol.setAttribute("class", "col-span-2 flex mt-1 mb-2");

  var add_more_fields = document.getElementById("add_more_fields_inv");

  var newField = document.createElement("input");
  newField.setAttribute("type", "text");
  newField.setAttribute("name", "our_costs_desc[]");
  newField.setAttribute("class", "form-input");
  newField.setAttribute("placeholder", "(Costs - XYZ)");
  divElmField.appendChild(newField);

  var newField1 = document.createElement("input");
  newField1.setAttribute("type", "number");
  newField1.setAttribute("step", "0.01");
  newField1.setAttribute("name", "our_costs[]");
  newField1.setAttribute("class", "form-input");
  newField1.setAttribute("placeholder", "£0.00");
  divElmField1.appendChild(newField1);

  var minusSign = document.createElement("span");
  minusSign.setAttribute("type", "button");
  minusSign.setAttribute("onclick", "removeField(this);");
  minusSign.setAttribute("class", "btn-danger px-4");
  minusSign.appendChild(document.createTextNode("-"));

  var plusSign = document.createElement("span");
  plusSign.setAttribute("type", "button");
  plusSign.setAttribute("onclick", "addFieldsInvoice('our_costs_row');");
  plusSign.setAttribute("class", "btn btn-primary px-4");
  plusSign.setAttribute("id", "add_more_fields_inv");
  plusSign.appendChild(document.createTextNode("+"));
  divElmFieldSymbol.appendChild(plusSign);

  parentNode = add_more_fields.parentNode;
  parentNode.replaceChild(minusSign, add_more_fields);

  divElmNewRow.appendChild(divElmField);
  divElmNewRow.appendChild(divElmField1);
  divElmNewRow.appendChild(divElmFieldSymbol);
  container.appendChild(divElmNewRow);
}

function removeField(minusElm) {
  minusElm.parentNode.parentNode.remove();
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
