function main(arg) {
  var data = JSON.parse(atob(arg));
  var type = data.MessageType;

  return {
      type: type,
      body: data
  };
}