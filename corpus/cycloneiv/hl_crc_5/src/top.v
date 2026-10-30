module top (
  input clk,
  output y
);
reg [7:0] crc1;
function [7:0] crcf2(input [7:0] cc, input [0:0] x);
  integer i; reg [7:0] rr;
  begin
    rr = cc;
    for (i = 0; i < 1; i = i + 1) rr = (rr[7] ^ x[0 - i]) ? ((rr << 1) ^ 8'h7) : (rr << 1);
    crcf2 = rr;
  end
endfunction
reg [31:0] stim0;
reg y_q;
always @(posedge clk) stim0 <= {stim0[30:0], ~(stim0[31] ^ stim0[21] ^ stim0[1] ^ stim0[0])};
always @(posedge clk) if (stim0[8] & stim0[11] & stim0[29]) crc1 <= {8{1'b1}}; else if (stim0[20]) crc1 <= crcf2(crc1, stim0[22]);
always @(posedge clk) y_q <= (^crc1);
assign y = y_q;
endmodule
