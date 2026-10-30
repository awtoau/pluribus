module top (
  input clk,
  output y
);
reg [15:0] crc1;
function [15:0] crcf2(input [15:0] cc, input [0:0] x);
  integer i; reg [15:0] rr;
  begin
    rr = cc;
    for (i = 0; i < 1; i = i + 1) rr = (rr[15] ^ x[0 - i]) ? ((rr << 1) ^ 16'h1021) : (rr << 1);
    crcf2 = rr;
  end
endfunction
reg [31:0] stim0;
reg y_q;
always @(posedge clk) stim0 <= {stim0[30:0], ~(stim0[31] ^ stim0[21] ^ stim0[1] ^ stim0[0])};
always @(posedge clk) if (stim0[22] & stim0[3] & stim0[28]) crc1 <= {16{1'b1}}; else if (stim0[2]) crc1 <= crcf2(crc1, stim0[14]);
always @(posedge clk) y_q <= (^crc1);
assign y = y_q;
endmodule
