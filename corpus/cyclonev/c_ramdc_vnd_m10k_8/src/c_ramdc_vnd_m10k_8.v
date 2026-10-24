module c_ramdc_vnd_m10k_8 (wclk, rclk, we, waddr, raddr, din, dout);
  input wclk, rclk, we;
  input [5:0] waddr, raddr;
  input [7:0] din;
  output [7:0] dout;
  reg [7:0] dout;
  (* ramstyle = "M10K" *) reg [7:0] mem [0:63];
  always @(posedge wclk) if (we) mem[waddr] <= din;
  always @(posedge rclk) dout <= mem[raddr];
endmodule
