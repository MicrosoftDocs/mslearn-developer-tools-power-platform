function main(arg) {
  var data = JSON.parse(atob(arg));
  var type = data.MessageType;

  var wrap = {
      type: type,
      body: null
  };

  if (type == "ua-data") {
    wrap.body = {
      "DmmDatasetMessage": [
        data
      ]
    };
  } else {
    wrap.body = data;
  }

  return wrap;
}