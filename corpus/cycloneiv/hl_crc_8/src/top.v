module top (
  input clk,
  output y
);
reg [31:0] crc1;
function [31:0] crcf2(input [31:0] cc, input [0:0] x);
  integer i; reg [31:0] rr;
  begin
    rr = cc;
    for (i = 0; i < 1; i = i + 1) rr = (rr[31] ^ x[0 - i]) ? ((rr << 1) ^ 32'h4C11DB7) : (rr << 1);
    crcf2 = rr;
  end
endfunction
reg [31:0] stim0;
reg [15:0] crc3;
function [15:0] crcf4(input [15:0] cc, input [7:0] x);
  integer i; reg [15:0] rr;
  begin
    rr = cc;
    for (i = 0; i < 8; i = i + 1) rr = (rr[15] ^ x[7 - i]) ? ((rr << 1) ^ 16'h1021) : (rr << 1);
    crcf4 = rr;
  end
endfunction
reg y_q;
always @(posedge clk) stim0 <= {stim0[30:0], ~(stim0[31] ^ stim0[21] ^ stim0[1] ^ stim0[0])};
always @(posedge clk) if (stim0[1] & stim0[22] & stim0[10]) crc1 <= {32{1'b1}}; else if (stim0[28]) crc1 <= crcf2(crc1, stim0[15]);
always @(posedge clk) if (stim0[9] & stim0[26] & stim0[11]) crc3 <= {16{1'b1}}; else if (stim0[23]) crc3 <= crcf4(crc3, {stim0[21], stim0[19], stim0[2], stim0[3], stim0[31], stim0[13], stim0[16], stim0[17]});
always @(posedge clk) y_q <= (^crc1) ^ (^crc3);
assign y = y_q;
endmodule
