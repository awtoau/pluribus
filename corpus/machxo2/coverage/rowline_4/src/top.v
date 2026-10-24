module top (clk,
  din_0, din_1, din_2, din_3, din_4, din_5, din_6, din_7,
  dout_0, dout_1, dout_2, dout_3, dout_4, dout_5, dout_6, dout_7);
  input clk;
  input din_0, din_1, din_2, din_3, din_4, din_5, din_6, din_7;
  output dout_0, dout_1, dout_2, dout_3, dout_4, dout_5, dout_6, dout_7;
  wire m_0;
  FD1S3AX #(.GSR("DISABLED")) f1_0 (.D(din_0), .CK(clk), .Q(m_0));
  FD1S3AX #(.GSR("DISABLED")) f2_0 (.D(m_0), .CK(clk), .Q(dout_0));
  wire m_1;
  FD1S3AX #(.GSR("DISABLED")) f1_1 (.D(din_1), .CK(clk), .Q(m_1));
  FD1S3AX #(.GSR("DISABLED")) f2_1 (.D(m_1), .CK(clk), .Q(dout_1));
  wire m_2;
  FD1S3AX #(.GSR("DISABLED")) f1_2 (.D(din_2), .CK(clk), .Q(m_2));
  FD1S3AX #(.GSR("DISABLED")) f2_2 (.D(m_2), .CK(clk), .Q(dout_2));
  wire m_3;
  FD1S3AX #(.GSR("DISABLED")) f1_3 (.D(din_3), .CK(clk), .Q(m_3));
  FD1S3AX #(.GSR("DISABLED")) f2_3 (.D(m_3), .CK(clk), .Q(dout_3));
  wire m_4;
  FD1S3AX #(.GSR("DISABLED")) f1_4 (.D(din_4), .CK(clk), .Q(m_4));
  FD1S3AX #(.GSR("DISABLED")) f2_4 (.D(m_4), .CK(clk), .Q(dout_4));
  wire m_5;
  FD1S3AX #(.GSR("DISABLED")) f1_5 (.D(din_5), .CK(clk), .Q(m_5));
  FD1S3AX #(.GSR("DISABLED")) f2_5 (.D(m_5), .CK(clk), .Q(dout_5));
  wire m_6;
  FD1S3AX #(.GSR("DISABLED")) f1_6 (.D(din_6), .CK(clk), .Q(m_6));
  FD1S3AX #(.GSR("DISABLED")) f2_6 (.D(m_6), .CK(clk), .Q(dout_6));
  wire m_7;
  FD1S3AX #(.GSR("DISABLED")) f1_7 (.D(din_7), .CK(clk), .Q(m_7));
  FD1S3AX #(.GSR("DISABLED")) f2_7 (.D(m_7), .CK(clk), .Q(dout_7));
endmodule
