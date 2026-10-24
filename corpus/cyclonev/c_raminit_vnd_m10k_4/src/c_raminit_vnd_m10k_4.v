module c_raminit_vnd_m10k_4 (clk, we, waddr, raddr, din, dout);
  input clk, we;
  input [5:0] waddr, raddr;
  input [3:0] din;
  output [3:0] dout;
  reg [3:0] dout;
  (* ramstyle = "M10K" *) reg [3:0] mem [0:63];
  integer i;
  initial for (i = 0; i < 64; i = i + 1) mem[i] = (i * 37 + 11) ^ (i >> 2) ^ (i * 9);
  always @(posedge clk) begin
    if (we) mem[waddr] <= din;
    dout <= mem[raddr];
  end
endmodule
