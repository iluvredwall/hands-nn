from tensorflow.python.ops import rnn_cell_impl, array_ops, math_ops, nn_ops, init_ops
from tensorflow.python.ops import variable_scope as vs

# from https://github.com/tensorflow/tensorflow/pull/8891

class ConvLSTMCell(rnn_cell_impl.RNNCell):
  """Convolutional LSTM recurrent network cell.
  https://arxiv.org/pdf/1506.04214v1.pdf
  """

  def __init__(self,
               input_shape,
               output_channels,
               kernel_shape,
               use_bias=True,
               skip_connection=False,
               forget_bias=1.0,
               initializers=None,
               name="conv_lstm_cell"):
    """Construct ConvLSTMCell.
    Args:
      input_shape: Shape of the input as int tuple, excluding the batch size.
      output_channels: int, number of output channels of the conv LSTM.
      kernel_shape: Shape of kernel as in tuple (of size 1,2 or 3).
      use_bias: Use bias in convolutions.
      skip_connection: If set to `True`, concatenate the input to the
      output of the conv LSTM. Default: `False`.
      forget_bias: Forget bias.
      name: Name of the module.
    Raises:
      ValueError: If `skip_connection` is `True` and stride is different from 1
        or if `input_shape` is incompatible with `conv_ndims`.
    """
    super(ConvLSTMCell, self).__init__(name=name)

    conv_ndims = len(kernel_shape)

    self._conv_ndims = conv_ndims
    self._input_shape = input_shape
    self._output_channels = output_channels
    self._kernel_shape = kernel_shape
    self._use_bias = use_bias
    self._forget_bias = forget_bias
    self._skip_connection = skip_connection

    self._total_output_channels = output_channels
    if self._skip_connection:
      self._total_output_channels += self._input_shape[-1]

  @property
  def output_size(self):
    return self._input_shape[:-1] + [self._total_output_channels]

  @property
  def state_size(self):
    return self._input_shape[:-1] + [self._output_channels]

  def zero_state(self, batch_size, dtype):
    shape = ([batch_size]
            + self._input_shape[:-1]
            + [self._total_output_channels])
    zero_cell = array_ops.zeros(shape, dtype=dtype)
    zero_hidden = array_ops.zeros(shape, dtype=dtype)
    zero_state = rnn_cell_impl.LSTMStateTuple(zero_cell, zero_hidden)
    return zero_state

  def call(self, inputs, state, scope=None):
    cell, hidden = state
    new_hidden = _conv([inputs, hidden],
                       self._kernel_shape,
                       4*self._output_channels,
                       self._use_bias)
    gates = array_ops.split(value=new_hidden,
                            num_or_size_splits=4,
                            axis=self._conv_ndims+1)

    input_gate, new_input, forget_gate, output_gate = gates
    new_cell = math_ops.sigmoid(forget_gate + self._forget_bias) * cell
    new_cell += math_ops.sigmoid(input_gate) * math_ops.tanh(new_input)
    output = math_ops.tanh(new_cell) * math_ops.sigmoid(output_gate)

    if self._skip_connection:
      output = array_ops.concat([output, inputs], axis=-1)
    new_state = rnn_cell_impl.LSTMStateTuple(new_cell, output)
    return output, new_state

def _conv(args,
          filter_size,
          num_features,
          bias,
          bias_start=0.0):
  """convolution:
  Args:
    args: a Tensor or a list of Tensors of dimension 3D, 4D or 5D,
    batch x n, Tensors.
    filter_size: int tuple of filter height and width.
    num_features: int, number of features.
    bias_start: starting value to initialize the bias; 0 by default.
  Returns:
    A 3D, 4D, or 5D Tensor with shape [batch ... num_features]
  Raises:
    ValueError: if some of the arguments has unspecified or wrong shape.
  """

  # Calculate the total size of arguments on dimension 1.
  total_arg_size_depth = 0
  shapes = [a.get_shape().as_list() for a in args]
  shape_length = len(shapes[0])
  for shape in shapes:
    if len(shape) not in [3,4,5]:
      raise ValueError("Conv Linear expects 3D, 4D or 5D arguments: %s" % str(shapes))
    if len(shape) != len(shapes[0]):
      raise ValueError("Conv Linear expects all args to be of same Dimensiton: %s" % str(shapes))
    else:
      total_arg_size_depth += shape[-1]
  dtype = [a.dtype for a in args][0]

  # determine correct conv operation
  if   shape_length == 3:
    conv_op = nn_ops.conv1d
    strides = 1
  elif shape_length == 4:
    conv_op = nn_ops.conv2d
    strides = shape_length*[1]
  elif shape_length == 5:
    conv_op = nn_ops.conv3d
    strides = shape_length*[1]

  # Now the computation.
  kernel = vs.get_variable(
      "kernel",
      filter_size + [total_arg_size_depth, num_features],
      dtype=dtype)
  if len(args) == 1:
    res = conv_op(args[0],
                  kernel,
                  strides,
                  padding="SAME")
  else:
   res = conv_op(array_ops.concat(axis=shape_length-1, values=args),
                 kernel,
                 strides,
                 padding="SAME")
  if not bias:
    return res
  bias_term = vs.get_variable(
      "biases", [num_features],
      dtype=dtype,
      initializer=init_ops.constant_initializer(
          bias_start, dtype=dtype))
  return res + bias_term